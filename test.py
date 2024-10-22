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

"""
    雷電模擬器:平板版(1280*720)
"""
# 初始化全局變量
keep_running = True  # 控制程序運行狀態

# 設置日誌記錄
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


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


def main():
    global keep_running
    
    stop_program_on_keypress()
    logging.info("程序開始執行")

    login = [f"./photo/{i}.png" for i in range(1, 6)]
    login1 = [f"./photo/{i}.png" for i in range(7, 13)]
    
    update = [f"./photo/{i}.png" for i in range(1, 3)]
    update1 = [f"./photo/{i}.png" for i in range(3, 6)]
    
    while keep_running:
        setup_adb()
        if click_images_in_sequence(update):
            tap(961, 257)
            tee, _, _ = check_image("./photo/teeth.png", (776, 111, 148, 165))
            if tee:
                logging.info("找到了")
            else:
                logging.info("沒找到")
                click_until_next_image((1146, 52), "./photo/teeth.png", region=(776, 111, 148, 165))
            swipe(841, 166, 420, 251)
            time.sleep(1)
            tap(92, 50)
            time.sleep(1)
            if click_images_in_sequence(update1):
                if click_until_next_image((704, 350), "./photo/monster.png"):
                    if find_and_click_image("./photo/monster.png"):
                        if click_until_next_image((704, 350), "./photo/boss.png"):
                            click_images_in_sequence(login1)

        time.sleep(2)
    
    logging.info("程序結束")

if __name__ == "__main__":
    main()