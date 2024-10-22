from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import random
import string
import requests

app = FastAPI()

# 這是模板所在的目錄
templates = Jinja2Templates(directory="templates")

API_URL = "https://api.guerrillamail.com/ajax.php"

def create_temp_email():
    params = {
        'f': 'get_email_address',
        'lang': 'en'
    }
    response = requests.get(API_URL, params=params)
    if response.status_code == 200:
        email_data = response.json()
        return email_data['email_addr'], email_data['sid_token']
    else:
        return None, None

def check_inbox(sid_token):
    params = {
        'f': 'check_email',
        'sid_token': sid_token,
        'seq': 0
    }
    response = requests.get(API_URL, params=params)
    if response.status_code == 200:
        return response.json().get('list', [])
    else:
        return []

def generate_random_string(length, use_digits, use_uppercase, use_lowercase):
    characters = ''
    if use_digits:
        characters += string.digits
    if use_uppercase:
        characters += string.ascii_uppercase
    if use_lowercase:
        characters += string.ascii_lowercase
    return ''.join(random.choice(characters) for _ in range(length))

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    email_address, sid_token = create_temp_email()
    return templates.TemplateResponse("index.html", {"request": request, "email": email_address, "sid_token": sid_token})

@app.get("/check-email")
async def check_email(sid_token: str):
    emails = check_inbox(sid_token)
    return {"emails": emails}

@app.get("/new-email")
async def new_email():
    email_address, sid_token = create_temp_email()
    return {"email": email_address, "sid_token": sid_token}

# 新增亂數生成 API
@app.get("/generate-random")
async def generate_random(groups: int = 1, length: int = 8, digits: bool = True, uppercase: bool = True, lowercase: bool = True):
    if groups < 1 or groups > 10 or length < 1 or length > 10:
        return {"error": "Groups and length should be between 1 and 10."}
    
    random_strings = []
    for _ in range(groups):
        random_string = generate_random_string(length, digits, uppercase, lowercase)
        random_strings.append(random_string)
    
    return {"random_strings": random_strings}
