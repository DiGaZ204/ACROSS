import subprocess
import time
import os
import datetime
import sys
import threading
import keyboard
import cv2
import numpy as np
from functools import lru_cache
import logging
import pytesseract
from fastapi import FastAPI, Form, Query
from fastapi.middleware.cors import CORSMiddleware
import webbrowser
from PyQt5.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget
from PyQt5.QtWebEngineWidgets import QWebEngineView
from PyQt5.QtCore import QUrl

"""
    雷電模擬器:平板版(1280*720)
"""
# 檢查是否在打包後運行
if getattr(sys, 'frozen', False):
    # 如果是打包後，使用 _MEIPASS
    current_dir = sys._MEIPASS
else:
    # 如果是原始腳本，使用當前文件路徑
    current_dir = os.path.dirname(os.path.abspath(__file__))

html_file_path = os.path.join(current_dir, 'index.html')
# 打開 HTML 檔案
# webbrowser.open(html_file_path)

# 初始化全局變量
keep_running = True
selected_choice = None
selected_sub_choice = None

# 初始化 FastAPI 應用
app = FastAPI()

# Allow CORS for all origins (for development)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
# 設置日誌記錄
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

@app.post("/process/")
async def process_selection(choice: str = Form(...), sub_choice: str = Form(None)):
    global selected_choice, selected_sub_choice
    if choice == "1" and sub_choice is None:
        return {"error": "需要進一步選擇"}
    
    selected_choice = choice
    selected_sub_choice = sub_choice if choice == "1" else "無"
    
    return {"selected_choice": selected_choice, "selected_sub_choice": selected_sub_choice}

@app.get("/get_selection/")
async def get_selection(choice: str = Query(...), sub_choice: str = Query(None)):
    global selected_choice, selected_sub_choice
    if choice == "1" and sub_choice is None:
        return {"error": "需要進一步選擇"}

    selected_choice = choice
    selected_sub_choice = sub_choice if choice == "1" else "無"

    print(f"選擇: {choice}, 進一步選擇: {selected_sub_choice}")
    return {"selected_choice": selected_choice, "selected_sub_choice": selected_sub_choice}

def setup_adb():
    """
    設置 ADB 連接
    """
    logging.info("啟動 ADB 服務器")
    subprocess.run("adb start-server", shell=True)
    
    # 獲取已連接設備列表
    devices = run_adb_command("devices")
    if "device" not in devices:
        logging.error("未檢測到已連接的設備，請確保模擬器已啟動並已連接。")
        sys.exit(1)
    
    logging.info("ADB 連接已建立。")

def stop_program():
    global keep_running
    keep_running = False
    logging.info("檢測到鍵盤輸入，程序將停止運行。")

def stop_program_on_keypress():
    keyboard.add_hotkey('`', stop_program)
    logging.info("已設置按下 'esc' 鍵以停止程序。")

def run_adb_command(command):
    """
    執行ADB命令
    """
    full_command = f"adb {command}"
    try:
        result = subprocess.run(full_command, shell=True, capture_output=True, text=True)
        if result.returncode != 0:
            logging.error(f"ADB命令執行失敗: {full_command}，錯誤信息: {result.stderr}")
        return result.stdout.strip()
    except Exception as e:
        logging.error(f"執行ADB命令出錯: {str(e)}")
        return None

def tap(x, y):
    """
    在指定坐標點擊
    """
    run_adb_command(f"shell input tap {x} {y}")
    logging.info(f"點擊坐標: ({x}, {y})")

def swipe(x1, y1, x2, y2, duration=500):
    """
    從一個坐標滑動到另一個坐標
    """
    run_adb_command(f"shell input swipe {x1} {y1} {x2} {y2} {duration}")
    logging.info(f"滑動: 從 ({x1}, {y1}) 到 ({x2}, {y2})")

@lru_cache(maxsize=10)
def load_image(image_path):
    """
    讀取並快取模板圖像
    """
    if not os.path.isfile(image_path):
        logging.error(f"文件不存在: {image_path}")
        return None
    return cv2.imread(image_path)

def capture_screen():
    try:
        result = subprocess.run("adb exec-out screencap -p", shell=True, capture_output=True)
        screen_np = np.frombuffer(result.stdout, np.uint8)
        return cv2.imdecode(screen_np, cv2.IMREAD_COLOR)
    except Exception as e:
        logging.error(f"無法捕獲螢幕畫面: {str(e)}")
        return None

def check_image(image_path, region=None):
    """
    在螢幕上檢測圖像是否存在
    """
    try:
        screen = capture_screen()
        if screen is None:
            logging.error("無法捕獲螢幕畫面")
            return False, None, None

        if region:
            x, y, w, h = region
            screen = screen[y:y + h, x:x + w]

        template = load_image(image_path)
        if template is None:
            return False, None, None

        result = cv2.matchTemplate(screen, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)
        
        if max_val >= 0.8:
            if region:
                max_loc = (max_loc[0] + x, max_loc[1] + y)
            return True, max_loc, template.shape
        return False, None, None
    except Exception as e:
        logging.error(f"圖像處理過程中發生錯誤: {str(e)}")
        return False, None, None

def find_and_click_image(image_path, max_attempts=100, delay=0.1, region=None):
    """
    找到屏幕上的圖像並點擊
    """
    for attempt in range(max_attempts):
        if not keep_running:
            logging.info("程序停止中...")
            return False

        found, location, shape = check_image(image_path, region)
        if found:
            center_x = location[0] + shape[1] // 2
            center_y = location[1] + shape[0] // 2
            tap(center_x, center_y)
            logging.info(f"找到並點擊了圖像: {image_path} at {center_x}, {center_y}")
            time.sleep(delay)
            return True
        else:
            logging.info(f"未找到圖像，嘗試 {attempt + 1}/{max_attempts}，將重試...")
            time.sleep(delay)
    
    logging.error(f"在 {max_attempts} 次嘗試後仍未找到匹配的圖像: {image_path}")
    return False

def click_images_in_sequence(image_paths, max_attempts=50, delay=0.5, region=None):
    """
    依序點擊多張圖片
    """
    for i, image_path in enumerate(image_paths, 1):
        if not keep_running:
            logging.info("程序停止中...")
            return False

        if not os.path.isfile(image_path):
            logging.error(f"文件不存在: {image_path}")
            continue
        
        logging.info(f"正在嘗試點擊第 {i} 張圖片: {image_path}")
        if find_and_click_image(image_path, max_attempts=max_attempts, delay=delay, region=region):
            logging.info(f"成功點擊第 {i} 張圖片: {image_path}")
        else:
            logging.warning(f"無法點擊第 {i} 張圖片: {image_path}，繼續下一張")
        time.sleep(delay)
    return True

def click_until_next_image(click_coords, next_image_path, max_attempts=50, delay=2, region=None):
    """
    持續點擊指定坐標，直到能夠檢測到下一張圖片
    """
    for attempt in range(max_attempts):
        if not keep_running:
            logging.info("程序停止中...")
            return False

        tap(click_coords[0], click_coords[1])
        logging.info(f"嘗試 {attempt + 1}/{max_attempts}")
        
        found, _, _ = check_image(next_image_path, region)
        if found:
            logging.info(f"檢測到下一張圖片: {next_image_path}")
            return True
        
        time.sleep(delay)
    
    logging.error(f"在 {max_attempts} 次嘗試後仍未檢測到下一張圖片。")
    return False

def click_and_print_coordinates():
    """
    捕獲螢幕並打印點擊位置的座標
    """
    print("按任意位置來獲取座標，按 'q' 鍵退出。")

    # 使用 ADB 捕獲螢幕
    screen = capture_screen()

    if screen is None:
        print("無法捕獲螢幕畫面")
        return
    
    # 定義滑鼠點擊事件
    def mouse_callback(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            print(f"點擊座標: ({x}, {y})")
    
    # 顯示捕獲的螢幕
    cv2.namedWindow("screen")
    cv2.setMouseCallback("screen", mouse_callback)

    while True:
        cv2.imshow("screen", screen)
        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

def press_key(key, duration=1):
    """
    模擬按鍵按下和釋放
    :param key: 按鍵的字符
    :param duration: 按下的持續時間（秒）
    """
    run_adb_command(f"shell input text {key}")
    logging.info(f"按下按鍵: {key} 持續時間: {duration} 秒")
    time.sleep(duration)
    # 釋放按鍵不需要額外的命令，因為 `input text` 命令會自動完成按下和釋放

def calculate_region(points):
    """
    計算包含所有指定點的最小矩形區域
    """
    min_x = min(point[0] for point in points)
    max_x = max(point[0] for point in points)
    min_y = min(point[1] for point in points)
    max_y = max(point[1] for point in points)
    return (min_x, min_y, max_x - min_x, max_y - min_y)

def check_number_in_region(region):
    """
    檢查指定區域中的數字
    :param region: 檢查的區域 (x, y, w, h)
    :return: 提取的數字
    """
    try:
        screen = capture_screen()
        if screen is None:
            logging.error("無法捕獲螢幕畫面")
            return None

        x, y, w, h = region
        screen_region = screen[y:y + h, x:x + w]

        # 使用 pytesseract 進行 OCR
        text = pytesseract.image_to_string(screen_region, config='--psm 6 digits')
        logging.info(f"檢測到的數字: {text.strip()}")
        return text.strip()
    except Exception as e:
        logging.error(f"OCR 過程中發生錯誤: {str(e)}")
        return None

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # 設定窗口標題和大小
        self.setWindowTitle("崩鐵周回腳本")
        self.setGeometry(100, 100, 800, 600)

        # 創建一個中央小部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 創建一個垂直佈局
        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        # 創建一個Web引擎視圖以顯示HTML內容
        self.browser = QWebEngineView()
        layout.addWidget(self.browser)

        # 獲取 HTML 檔案的完整路徑
        if getattr(sys, 'frozen', False):
            # 如果是打包後，使用 _MEIPASS
            current_dir = sys._MEIPASS
        else:
            # 如果是原始腳本，使用當前文件路徑
            current_dir = os.path.dirname(os.path.abspath(__file__))

        html_file_path = os.path.join(current_dir, 'index.html')

        # 載入 HTML 文件，轉換為 QUrl 對象
        self.browser.setUrl(QUrl.fromLocalFile(html_file_path))
        
def main():
    global keep_running, selected_choice, selected_sub_choice
    stop_program_on_keypress()
    logging.info("程序開始執行")

    send = os.path.join(current_dir, 'photoForStar_Rail', 'send.png')
    first = os.path.join(current_dir, 'photoForStar_Rail', 'first.png')
    startTo = os.path.join(current_dir, 'photoForStar_Rail', 'startTo.png')
    universe = os.path.join(current_dir, 'photoForStar_Rail', 'universe.png')
    exit = os.path.join(current_dir, 'photoForStar_Rail', 'exit.png')
    again = os.path.join(current_dir, 'photoForStar_Rail', 'again.png')

    setup_adb()

    while keep_running:
        logging.info(f"當前選擇: {selected_choice}, 進一步選擇: {selected_sub_choice}")

        if selected_choice:
            find_and_click_image(first)
            if selected_sub_choice == "1":
                find_and_click_image(send, region=(1004, 335, 166, 98))
            elif selected_sub_choice == "2":
                find_and_click_image(send, region=(1010, 430, 162, 104))
            elif selected_sub_choice == "3":
                find_and_click_image(send, region=(1008, 534, 162, 92))
            else:
                swipe(657, 583, 657, 308, 3100)
                swipe(657, 583, 657, 308, 3100)
                time.sleep(1)
                if selected_sub_choice == "4":
                    find_and_click_image(send, region=(1004, 335, 166, 98))
                elif selected_sub_choice == "5":
                    find_and_click_image(send, region=(1010, 430, 162, 104))
                elif selected_sub_choice == "6":
                    find_and_click_image(send, region=(1008, 534, 162, 92))
                else:
                    swipe(657, 583, 657, 300, 2800)
                    time.sleep(1)
                    if selected_sub_choice == "7":
                        find_and_click_image(send, region=(1004, 335, 166, 98))
                    elif selected_sub_choice == "8":
                        find_and_click_image(send, region=(1010, 430, 162, 104))
                    elif selected_sub_choice == "9":
                        find_and_click_image(send, region=(1008, 534, 162, 92))
            
            if find_and_click_image(startTo):
                time.sleep(3)
                tee, _, _ = check_image(universe)
                if tee:
                    logging.info("成功進入差分宇宙!")
                else:
                    click_until_next_image((704, 350), universe)
                swipe(246, 561, 246, 422, duration=3000)
                tap(1064, 552)
                tee, _, _ = check_image(exit)
                if tee:
                    logging.info("成功進入差分宇宙!")
                else:
                    click_until_next_image((1094, 334), exit)
                next = input("請輸入選擇: 1.繼續 2.退出: ")
                if next == "1":
                    find_and_click_image(again)
                elif next == "2":
                    find_and_click_image(exit)
                    break
            
    logging.info("程序結束")

# 啟動 FastAPI 服務和主邏輯程式的多線程執行
def start_fastapi():
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)

if __name__ == "__main__":
    # click_and_print_coordinates()

    # 加載圖片
    # image_path = os.path.join(current_dir, "photoForStar_Rail", "first.png")
    # if os.path.exists(image_path):
    #     # 使用 OpenCV 加載並顯示圖片
    #     print(f"正在加載圖片: {image_path}")
    #     img = cv2.imread(image_path)

    #     # 顯示圖片
    #     cv2.imshow("圖片顯示", img)

    #     # 等待按鍵以關閉窗口
    #     cv2.waitKey(0)
    #     cv2.destroyAllWindows()
    # else:
    #     print(f"文件不存在: {image_path}")
    

    # 啟動 FastAPI 服務的線程
    fastapi_thread = threading.Thread(target=start_fastapi)
    fastapi_thread.start()
    app1 = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app1.exec_())
    main()
    