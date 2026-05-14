import os
import json
import random
import io
import docx
import urllib.request
import csv
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()
from fastapi import FastAPI, Request, Form, Depends, UploadFile, File
from fastapi.responses import RedirectResponse, HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
import google.oauth2.credentials
import google_auth_oauthlib.flow
from googleapiclient.discovery import build

app = FastAPI()

# تفعيل مجلد الصور (الشعار)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Session middleware لتخزين بيانات المستخدم المسجل مؤقتاً
app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET", "super-secret-key-change-in-production"))

templates = Jinja2Templates(directory="templates")

CLIENT_SECRETS_FILE = "client_secret.json"

# الصلاحيات التي نطلبها من المستخدم عند تسجيل الدخول
SCOPES = [
    'https://www.googleapis.com/auth/forms.body',
    'openid', 
    'https://www.googleapis.com/auth/userinfo.email', 
    'https://www.googleapis.com/auth/userinfo.profile'
]

# مفاتيح Gemini (سيتم تدويرها تلقائياً)
GEMINI_KEYS = [
    os.getenv("GEMINI_KEY_1"),
    os.getenv("GEMINI_KEY_2")
]

# منع مشكلة HTTPS في بيئة التطوير المحلية فقط
if os.getenv("ENV") == "development":
    os.environ['OAUTHLIB_INSECURE_TRANSPORT'] = '1'

def extract_json_from_text(title, desc, text):
    """دالة تقوم بإرسال النص للذكاء الاصطناعي وتستخرج الأسئلة بصيغة JSON"""
    keys = [k for k in GEMINI_KEYS if k and not k.startswith("YOUR_GEMINI")]
    
    if not keys:
        # حالة عدم وجود مفاتيح (ترجع سؤال تجريبي)
        return {
            "title": title,
            "description": desc,
            "questions": [
                { "type": "RADIO", "text": "لم يتم إدخال مفاتيح Gemini بعد. هذا سؤال تجريبي.", "options": ["نعم", "لا"] }
            ]
        }
        
    random.shuffle(keys)
    
    prompt = f"""
    لديك استبيان بحثي باللغة العربية.
    العنوان: {title}
    الوصف: {desc}
    النص الخام للأسئلة:
    {text}
    
    استخرج الأسئلة وحولها إلى مصفوفة JSON دقيقة. 
    يجب أن يكون الناتج النهائي JSON فقط بدون أي نصوص إضافية، بالشكل التالي:
    {{
      "title": "{title}",
      "description": "{desc}",
      "questions": [
        {{
          "type": "RADIO",
          "text": "سؤال اختيار من متعدد أو نعم/لا؟",
          "options": ["خيار 1", "خيار 2"],
          "has_other": false
        }},
        {{
          "type": "CHECKBOX",
          "text": "سؤال يمكن اختيار أكثر من إجابة فيه؟",
          "options": ["أ", "ب", "ج"],
          "has_other": true
        }},
        {{
          "type": "DROP_DOWN",
          "text": "سؤال قائمة منسدلة؟",
          "options": ["عنصر 1", "عنصر 2"]
        }},
        {{
          "type": "PARAGRAPH",
          "text": "سؤال مقالي طويل؟"
        }}
      ]
    }}
    أنواع الأسئلة المدعومة: 
    - RADIO: اختيار إجابة واحدة فقط (مثل نعم/لا، أو خيارات متعددة).
    - CHECKBOX: مربعات اختيار (استخدمه تلقائياً إذا كان السؤال يوحي باختيار أكثر من إجابة).
    - DROP_DOWN: قائمة منسدلة (استخدمه تلقائياً بدلاً من RADIO إذا كانت الخيارات كثيرة وتزيد عن 6 خيارات، مثل الجنسيات أو المناطق، للحفاظ على ترتيب النموذج).
    - TEXT: إجابة نصية قصيرة (مثل الاسم أو العمر أو التخصص).
    - PARAGRAPH: إجابة نصية طويلة (استخدمه تلقائياً إذا كان السؤال يطلب رأياً أو شرحاً أو وصفاً).
    
    ملاحظة هامة: الذكاء الاصطناعي الخاص بك قوي، قم بتحليل سياق كل سؤال واختر النوع الأنسب تلقائياً حتى لو لم يصرح المستخدم بنوع السؤال.
    إذا كان السؤال يحتوي على خيار (أخرى) أو (غير ذلك)، اجعل "has_other": true، ولا تضف كلمة "غير ذلك" أو "أخرى" ضمن قائمة options.
    """
    
    last_error = None
    for key in keys:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={key}"
            headers = {'Content-Type': 'application/json'}
            payload = {
                "contents": [{"parts": [{"text": prompt}]}],
                "generationConfig": {"temperature": 0.2}
            }
            req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
            with urllib.request.urlopen(req) as response:
                result_json = json.loads(response.read().decode('utf-8'))
                
            result = result_json['candidates'][0]['content']['parts'][0]['text'].strip()
            if result.startswith("```json"):
                result = result[7:]
            if result.endswith("```"):
                result = result[:-3]
            
            try:
                parsed_data = json.loads(result.strip())
                return parsed_data
            except json.JSONDecodeError as e:
                print(f"JSON Decode Error: {e}")
                return {
                    "title": "استبيان تم إنشاؤه جزئياً (خطأ في التحليل)",
                    "description": "واجه الذكاء الاصطناعي مشكلة في تنسيق الإجابة. يرجى مراجعة الأسئلة.",
                    "questions": [{"title": "الرجاء إعادة صياغة الأسئلة والمحاولة مرة أخرى", "type": "PARAGRAPH", "options": []}]
                }
        except Exception as e:
            print(f"فشل المفتاح في تحليل النص. الخطأ: {e}")
            continue
            
    # إذا فشلت جميع المفاتيح
    return {
        "title": title,
        "description": desc,
        "questions": [
            { "type": "TEXT", "text": "حدث خطأ داخلي. يرجى المحاولة لاحقاً." }
        ]
    }

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    user_info = request.session.get('user_info')
    if user_info:
        return RedirectResponse(url="/dashboard")
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login")
async def login(request: Request):
    # دعم Vercel عن طريق جلب بيانات العميل من متغيرات البيئة إن وجدت
    client_secret_env = os.getenv("GOOGLE_CLIENT_SECRET")
    
    if client_secret_env:
        client_config = json.loads(client_secret_env)
        flow = google_auth_oauthlib.flow.Flow.from_client_config(client_config, scopes=SCOPES)
    else:
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES)
    
    # تحديد الرابط الديناميكي
    redirect_uri = str(request.base_url).rstrip('/') + "/auth/callback"
    
    # إصلاح مشكلة HTTP في Vercel (إذا كان البروتوكول https ولكنه يظهر http)
    if "vercel.app" in redirect_uri or request.headers.get("x-forwarded-proto") == "https":
        redirect_uri = redirect_uri.replace("http://", "https://")
        
    flow.redirect_uri = redirect_uri
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true')
    
    request.session['state'] = state
    if hasattr(flow, 'code_verifier'):
        request.session['code_verifier'] = flow.code_verifier
        
    return RedirectResponse(url=authorization_url)

@app.get("/auth/callback")
async def auth_callback(request: Request, state: str, code: str):
    if state != request.session.get('state'):
        return HTMLResponse("Invalid state parameter", status_code=400)
    
    client_secret_env = os.getenv("GOOGLE_CLIENT_SECRET")
    if client_secret_env:
        client_config = json.loads(client_secret_env)
        flow = google_auth_oauthlib.flow.Flow.from_client_config(client_config, scopes=SCOPES, state=state)
    else:
        flow = google_auth_oauthlib.flow.Flow.from_client_secrets_file(CLIENT_SECRETS_FILE, scopes=SCOPES, state=state)
        
    redirect_uri = str(request.base_url).rstrip('/') + "/auth/callback"
    if "vercel.app" in redirect_uri or request.headers.get("x-forwarded-proto") == "https":
        redirect_uri = redirect_uri.replace("http://", "https://")
        
    flow.redirect_uri = redirect_uri
    
    code_verifier = request.session.get('code_verifier')
    if code_verifier:
        flow.code_verifier = code_verifier
        
    flow.fetch_token(code=code)
    
    credentials = flow.credentials
    request.session['credentials'] = {
        'token': credentials.token,
        'refresh_token': credentials.refresh_token,
        'token_uri': credentials.token_uri,
        'client_id': credentials.client_id,
        'client_secret': credentials.client_secret,
        'scopes': credentials.scopes
    }
    
    oauth2_client = build('oauth2', 'v2', credentials=credentials)
    user_info = oauth2_client.userinfo().get().execute()
    request.session['user_info'] = user_info
    
    return RedirectResponse(url="/dashboard")

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    user_info = request.session.get('user_info')
    if not user_info:
        return RedirectResponse(url="/")
        
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "user_info": user_info
    })

@app.post("/create_form")
async def create_form(
    request: Request, 
    survey_title: str = Form(...),
    survey_desc: str = Form(""),
    raw_text: str = Form(""),
    file_upload: UploadFile = File(None)
):
    creds_dict = request.session.get('credentials')
    if not creds_dict:
        return RedirectResponse(url="/")
        
    credentials = google.oauth2.credentials.Credentials(**creds_dict)
    
    try:
        # 1. قراءة النص من الملف (إذا تم إرفاقه) أو من المربع النصي
        survey_text = raw_text
        if file_upload and file_upload.filename:
            content = await file_upload.read()
            if len(content) > 5 * 1024 * 1024:
                return HTMLResponse("<div dir='rtl' style='text-align:center; padding:20px;'><h2 style='color:red;'>الملف كبير جداً</h2><p>الحد الأقصى المسموح به هو 5 ميجابايت.</p></div>", status_code=400)
            
            if file_upload.filename.endswith('.docx') or file_upload.filename.endswith('.doc'):
                doc = docx.Document(io.BytesIO(content))
                survey_text = "\n".join([p.text for p in doc.paragraphs if p.text.strip()])
            else:
                survey_text = content.decode('utf-8')
        if not survey_text.strip():
            survey_text = "لم يتم توفير أي أسئلة."
            
        # 2. تحليل النص واستخراج الـ JSON عبر الذكاء الاصطناعي
        data = extract_json_from_text(survey_title, survey_desc, survey_text)
        
        # 3. بناء النموذج في جوجل درايف
        form_service = build('forms', 'v1', credentials=credentials)
        
        form_body = {
            "info": {
                "title": data.get('title', survey_title),
                "documentTitle": data.get('title', survey_title)
            }
        }
        result = form_service.forms().create(body=form_body).execute()
        form_id = result["formId"]
        
        # 4. تسجيل حركة المستخدم (Analytics)
        try:
            user_info = request.session.get('user_info', {})
            log_email = user_info.get("email", "مجهول")
            file_exists = os.path.exists("users_log.csv")
            with open("users_log.csv", "a", encoding="utf-8-sig", newline="") as f:
                writer = csv.writer(f)
                if not file_exists:
                    writer.writerow(["تاريخ الإنشاء", "البريد الإلكتروني", "عنوان الاستبيان", "معرف النموذج (ID)"])
                writer.writerow([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), log_email, survey_title, form_id])
        except Exception as log_e:
            print(f"Failed to log user data: {log_e}")
            
        description = data.get('description', survey_desc)
        if description:
            update_body = {
                "requests": [{
                    "updateFormInfo": {
                        "info": {"description": description},
                        "updateMask": "description"
                    }
                }]
            }
            form_service.forms().batchUpdate(formId=form_id, body=update_body).execute()
        
        questions = data.get('questions', [])
        requests = []
        for i, q in enumerate(questions):
            q_type = q.get('type')
            item = {"title": q.get('text')}
            
            if q_type in ['RADIO', 'CHECKBOX', 'DROP_DOWN']:
                options = [{"value": opt} for opt in q.get('options', [])]
                if q.get('has_other'):
                    options.append({"isOther": True})
                    
                item["questionItem"] = {
                    "question": {
                        "required": True,
                        "choiceQuestion": {
                            "type": q_type,
                            "options": options
                        }
                    }
                }
            elif q_type == 'TEXT':
                item["questionItem"] = {
                    "question": {
                        "required": True,
                        "textQuestion": {"paragraph": False}
                    }
                }
            elif q_type == 'PARAGRAPH':
                item["questionItem"] = {
                    "question": {
                        "required": True,
                        "textQuestion": {"paragraph": True}
                    }
                }
            requests.append({
                "createItem": {
                    "item": item,
                    "location": {"index": i}
                }
            })
            
        if requests:
            body = {"requests": requests}
            form_service.forms().batchUpdate(formId=form_id, body=body).execute()
            
        form_url = f"https://docs.google.com/forms/d/{form_id}/edit"
        
        return templates.TemplateResponse("success.html", {
            "request": request,
            "form_url": form_url
        })
        
    except Exception as e:
        return HTMLResponse(f"حدث خطأ أثناء الإنشاء: {str(e)}", status_code=500)

@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse(url="/")

@app.get("/admin/logs")
async def download_logs(secret: str = ""):
    admin_secret = os.getenv("ADMIN_SECRET", "SmartAdmin2026")
    if secret != admin_secret:
        return HTMLResponse("<div dir='rtl' style='text-align:center; padding:50px; font-family:Arial;'><h2 style='color:red;'>غير مصرح لك بالوصول! 🛑</h2></div>", status_code=403)
        
    if not os.path.exists("users_log.csv"):
        return HTMLResponse("<div dir='rtl' style='text-align:center; padding:50px; font-family:Arial;'><h2>لم يقم أي شخص بإنشاء استبيان حتى الآن! 🤷‍♂️</h2></div>", status_code=404)
        
    return FileResponse(path="users_log.csv", filename="smart_forms_users_log.csv", media_type="text/csv")
