import os
import cv2
import numpy as np
import tensorflow as tf
import pytesseract
import re
from django.shortcuts import render
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from tensorflow.keras.applications.densenet import preprocess_input
from langgraph.graph import StateGraph, END
from typing import TypedDict, List, Dict
import requests
import urllib3
# Suppress the security warning in your terminal so it doesn't get messy
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from .models import DiagnosticRecord, ChatLog
from .blood_processor import extract_blood_data

# IMPORTANT FOR WINDOWS: Point this to where you installed Tesseract-OCR
import sys

# Detect if running on Windows (Local) or Linux (Render)
if sys.platform.startswith('win'):
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
else:
    pytesseract.pytesseract.tesseract_cmd = '/usr/bin/tesseract'

# MATCHING EXACT FILE NAMES
PNEUMONIA_MODEL_PATH = os.path.join(settings.BASE_DIR, 'models', 'densenet121_chest_xray.keras')
ECG_MODEL_PATH       = os.path.join(settings.BASE_DIR, 'models', 'best_ecg_densenet.keras')
KIDNEY_MODEL_PATH    = os.path.join(settings.BASE_DIR, 'models', 'kidney_model.keras')

# Model Cache
LOADED_MODELS = {}

def load_keras_model(model_key, model_path):
    if model_key not in LOADED_MODELS:
        if os.path.exists(model_path):
            LOADED_MODELS[model_key] = tf.keras.models.load_model(model_path)
        else:
            return None
    return LOADED_MODELS[model_key]

# --- TIER 1 DEFENSE: HYBRID OCR & PIXEL GATEKEEPER ---
# --- TIER 1 DEFENSE: HYBRID OCR & PIXEL GATEKEEPER ---
def passes_visual_gatekeeper(image_path, model_type):
    """
    Uses Tesseract OCR to definitively catch text-heavy Blood Reports, 
    and uses physical contrast (Standard Deviation) to separate ECGs from X-Rays.
    """
    img_raw = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img_raw is None:
        return False, "Unreadable image file."

    # Standardize size for consistent OCR and pixel math
    img = cv2.resize(img_raw, (800, 800))
    
    # 1. TESSERACT OCR TEXT DETECTOR
    extracted_text = pytesseract.image_to_string(img)
    char_count = len(re.findall(r'[a-zA-Z0-9]', extracted_text))
    
    # 2. BLACKNESS, BRIGHTNESS & CONTRAST METRICS
    total_pixels = img.size
    dark_ratio = np.sum(img < 40) / total_pixels
    mean_brightness = np.mean(img)
    
    # NEW: Standard Deviation measures the "flatness" of the image
    contrast = np.std(img)
    
    left_border = img[:, :int(800*0.15)]
    right_border = img[:, int(800*0.85):]
    side_darkness = (np.sum(left_border < 20) + np.sum(right_border < 20)) / (left_border.size + right_border.size)

    # --- GLOBAL RULE: BLOCK BLOOD REPORTS ---
    if char_count > 200:
        return False, f"SECURITY BLOCK: {char_count} text characters detected. You likely uploaded a Blood Report."

    # --- 1. ECG RULES ---
    if model_type == 'ecg':
        if dark_ratio > 0.20 or side_darkness > 0.30:
            return False, "SECURITY BLOCK: Image has heavy dark shadows. You likely uploaded an X-Ray or Ultrasound."

    # --- 2. KIDNEY ULTRASOUND RULES ---
    elif model_type == 'kidney':
        if mean_brightness > 100 or dark_ratio < 0.15:
            return False, "SECURITY BLOCK: Image is too bright overall to be an Ultrasound. You likely uploaded an X-Ray."

    # --- 3. PNEUMONIA (X-RAY) RULES ---
    elif model_type == 'pneumonia':
        if side_darkness > 0.50:
            return False, "SECURITY BLOCK: Massive dark borders detected. You likely uploaded an Ultrasound."
            
        # THE FIX: ECGs are flat paper (low contrast), X-Rays are deep anatomical scans (high contrast)
        if contrast < 45:
            return False, "SECURITY BLOCK: Image lacks anatomical depth/contrast. You likely uploaded a flat paper document (ECG)."
            
        # Backup check for bright, cleanly lit paper
        if dark_ratio < 0.02 and mean_brightness > 90:
            return False, "SECURITY BLOCK: Image lacks dark contrast (lungs). You likely uploaded an ECG."

    return True, "Image passed security checks."
# --- TIER 2 DEFENSE: HARDENED AI INFERENCE LOGIC ---
# (Keep your run_pneumonia_inference and everything below exactly as it is)
         
# --- TIER 2 DEFENSE: HARDENED AI INFERENCE LOGIC ---
def run_pneumonia_inference(image_path):
    model = load_keras_model('pneumonia', PNEUMONIA_MODEL_PATH)
    if not model:
        return {"diagnosis": "Error", "details": "Pneumonia model file not found."}
    
    img = tf.keras.utils.load_img(image_path, target_size=(224, 224))
    img_array = tf.keras.utils.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    prediction = model.predict(img_array)[0][0]
    
    # Relaxed 55% Confidence Gate
    confidence_score = max(prediction, 1.0 - prediction)
    if confidence_score < 0.45:
        return {
            "diagnosis": "System Block: AI Rejection", 
            "details": f"SECURITY BLOCK: AI Confidence is critically low ({confidence_score * 100:.2f}%). The neural network mathematically rejected this image as Out-of-Distribution data."
        }

    result = "Pneumonia Detected" if prediction > 0.5 else "Normal (No Pneumonia)"
    return {"diagnosis": result, "details": f"Diagnosis: {result}\nAI Confidence Score: {confidence_score * 100:.2f}%"}


def run_ecg_inference(image_path):
    model = load_keras_model('ecg', ECG_MODEL_PATH)
    if not model:
        return {"diagnosis": "Error", "details": "ECG model file missing."}
    
    img = tf.keras.utils.load_img(image_path, target_size=(512, 512))
    img_array = tf.keras.utils.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    processed_img = preprocess_input(img_array)

    raw_preds = model.predict(processed_img)[0]
    
    # Strict 60% Confidence Gate for 5-class model
    max_confidence = np.max(raw_preds)
    if max_confidence < 0.60:
        return {
            "diagnosis": "System Block: AI Rejection",
            "details": f"SECURITY BLOCK: AI Confidence is critically low ({max_confidence * 100:.2f}%). \n\nThis image bypassed the visual gatekeeper, but the Neural Network mathematically rejected it as a non-ECG image."
        }

    class_labels = ['NORM', 'MI', 'STTC', 'CD', 'HYP']
    results = list(zip(class_labels, raw_preds))
    results.sort(key=lambda x: x[1], reverse=True)

    report_lines = ["MULTI-LABEL ECG DIAGNOSTIC REPORT", "-" * 45]
    detected_diagnoses = []

    for label, prob in results:
        status = "POSITIVE" if prob >= 0.5 else "Negative"
        if status == "POSITIVE" and label != "NORM": detected_diagnoses.append(label)
        report_lines.append(f"** {label:<4} : {prob * 100:>6.2f}%  --> {status}")

    report_lines.append("-" * 45)
    diagnoses_str = ", ".join(detected_diagnoses) if detected_diagnoses else ("NORM" if next((p for l, p in results if l == "NORM"), 0) >= 0.5 else "None Detected")
    report_lines.append(f"DIAGNOSES DETECTED: {diagnoses_str}")

    return {"diagnosis": f"DIAGNOSES: {diagnoses_str}", "details": "\n".join(report_lines)}


def run_kidney_inference(image_path):
    model = load_keras_model('kidney', KIDNEY_MODEL_PATH)
    if not model:
        return {"diagnosis": "Error", "details": "Kidney stone model missing."}
    
    img = tf.keras.utils.load_img(image_path, target_size=(224, 224))
    img_array = tf.keras.utils.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    prediction = model.predict(img_array)[0][0]
    
    # Strict 70% Confidence Gate
    confidence_score = max(prediction, 1.0 - prediction)
    if confidence_score < 0.70:
        return {
            "diagnosis": "System Block: AI Rejection", 
            "details": f"SECURITY BLOCK: AI Confidence is critically low ({confidence_score * 100:.2f}%). The neural network mathematically rejected this image as Out-of-Distribution data."
        }

    result = "Kidney Stone Detected" if prediction > 0.5 else "No Kidney Stone Detected"
    return {"diagnosis": result, "details": f"Diagnosis: {result}\nAI Confidence Score: {confidence_score * 100:.2f}%"}

# --- VIEW CONTROLLER ---
def index(request):
    result = None
    uploaded_file_url = None

    if request.method == 'POST' and request.FILES.get('medical_image'):
        model_type = request.POST.get('model_type')
        uploaded_file = request.FILES['medical_image']
        
        p_name = request.POST.get('patient_name', 'Unknown Patient')
        p_age = request.POST.get('patient_age') or None
        p_sex = request.POST.get('patient_sex', 'Not Specified')

        record = DiagnosticRecord.objects.create(
            patient_name=p_name, patient_age=p_age, patient_sex=p_sex,
            model_type=model_type, image=uploaded_file
        )

        file_path = record.image.path
        uploaded_file_url = record.image.url

        if model_type in ['pneumonia', 'ecg', 'kidney']:
            passed, gatekeeper_message = passes_visual_gatekeeper(file_path, model_type)
            
            if not passed:
                result = {
                    "diagnosis": "System Block: Out-of-Distribution Data",
                    "details": gatekeeper_message
                }
            else:
                if model_type == 'pneumonia': result = run_pneumonia_inference(file_path)
                elif model_type == 'ecg': result = run_ecg_inference(file_path)
                elif model_type == 'kidney': result = run_kidney_inference(file_path)

        elif model_type == 'blood_report':
            result = extract_blood_data(file_path)

        if result:
            record.diagnosis_status = result.get('diagnosis', 'Error')
            record.detailed_report = result.get('details', '')
            record.save()
            
            # --- ADD THESE TWO LINES ---
            # This saves the AI diagnosis so the chatbot can read it later
            request.session['clinical_context'] = f"Diagnosis: {record.diagnosis_status}\nDetails: {record.detailed_report}"
            request.session.modified = True

    return render(request, 'diagnostics/index.html', {
        'result': result, 'uploaded_file_url': uploaded_file_url
    })
    
# 1. Define the State (The memory passed between nodes)
from typing import TypedDict, List, Dict

class AgentState(TypedDict):
    user_message: str
    chat_history: List[Dict[str, str]]
    ai_response: str
    is_safe: bool
    loop_count: int
    clinical_context: str  # <--- ADD THIS LINE
# 2. Define Node A: The LLM API Caller
def generate_medical_response(state: AgentState):
    api_key = "GROQ_API_KEY"  # Keep your actual Groq key here
    url = os.environ.get("GROQ_API_URL")
    
    # 1. Keep your existing persona string
    persona = f"""
You are NexMed AI, the dedicated navigational, technical, and clinical assistant for the NexMed Diagnostic Platform.

YOUR CAPABILITIES & INSTRUCTIONS:
1. PLATFORM NAVIGATION & UPLOADS: Guide users step-by-step on how to use NexMed. Instruct them to select the correct diagnostic tab (X-Ray, ECG, Kidney, or Blood Report), upload a clear, well-lit image of their medical scan, fill in patient details, and click 'Analyze'.
2. TROUBLESHOOTING HELPER: If a user reports an error or a rejected image, explain that NexMed's Tier-1 security gatekeeper blocks blurry, dark, or out-of-distribution files to prevent incorrect AI predictions. Advise them to re-upload a clear, flat, and correctly cropped image of the exact test requested.
3. EMERGENCY & LOCAL HEALTHCARE: The user is operating from Amritsar, Punjab, India. 
- If they report severe symptoms (chest pain, shortness of breath) or ask for emergency help, immediately provide the Indian National Emergency Number (112) and Ambulance Service (108).
- If they ask for nearby doctors or hospitals, check if they mentioned a specific city or location. If they did, recommend 2-3 major, highly-rated hospitals in that specific area. 
- If they ask for nearby hospitals but haven't specified their location, politely ask them what city they are currently in so you can provide accurate local recommendations.
4. CLINICAL EDUCATION: Explain NexMed's specific diagnostic modules (DenseNet Pneumonia, Multi-label ECG, Kidney Ultrasound, CBC OCR) clearly and concisely.

---
CURRENT PATIENT SCAN RESULTS:
{state.get('clinical_context', 'No scan results available yet.')}

If the user asks about their results or if they are concerning, refer to the scan results above. Always remind them that this is an AI analysis and they must consult a licensed physician.

STRICT BOUNDARY RULES:
- NEVER prescribe medication, provide personal diagnoses, or use phrases like "you have" or "my diagnosis is".
- If a user asks non-medical/non-NexMed questions, politely state your scope and decline.
- Keep responses professional, supportive, and limited to 2-3 short paragraphs.
"""
    
    # 2. Build the messages list starting with the system prompt
    messages = [{"role": "system", "content": persona.strip()}]
    
    # 3. INJECT THE MEMORY: Loop through chat_history and add previous turns
    for past_msg in state.get("chat_history", []):
        messages.append(past_msg)
        
    # 4. Handle safety correction
    correction = ""
    if state.get("loop_count", 0) > 0:
        correction = "\nREWRITE WARNING: Your prior output violated boundaries. Refrain from prescribing."
        
    # 5. Add the current user question at the very end
    messages.append({"role": "user", "content": f"{state['user_message']}{correction}"})

    # 6. Send the full package to Groq
    payload = {
        "model": "qwen/qwen3.8-27b",
        "messages": messages,
        "temperature": 0.3
    }

    headers = {
        'Authorization': f'Bearer {api_key}', 
        'Content-Type': 'application/json'
    }

    try:
        res = requests.post(url, headers=headers, json=payload, timeout=30, verify=False)
        res_json = res.json()
        
        if res.status_code != 200:
            error_msg = res_json.get('error', {}).get('message', 'API Error')
            return {"ai_response": f"NexMed Core Error: {error_msg}"}
            
        ai_reply = res_json['choices'][0]['message']['content']
        return {"ai_response": ai_reply}
        
    except Exception as e:
        return {"ai_response": f"System Crash: {str(e)}"}
# 3. Define Node B: The Clinical Safety Gatekeeper
# 3. Define Node B: The Clinical Safety Gatekeeper
def check_safety(state: AgentState):
    # Updated to prevent false positives while still blocking actual medical advice
    dangerous_keywords = [
        "i prescribe", 
        "take this medication", 
        "my diagnosis is", 
        "your diagnosis is", 
        "you are suffering from",
        "recommended dosage"
    ]
    reply = state["ai_response"].lower()
    
    # Check if the AI hallucinated and tried to act like a real doctor
    is_safe = not any(word in reply for word in dangerous_keywords)
    
    return {
        "is_safe": is_safe,
        "loop_count": state.get("loop_count", 0) + 1
    }

# 4. Define the Routing Logic
def route_safety(state: AgentState):
    if state["is_safe"]:
        return "end" # Safe! Send to the patient.
    if state["loop_count"] >= 2:
        return "end" # Prevent infinite loops if the AI refuses to comply.
    return "rewrite" # Unsafe! Route back to the LLM to rewrite.

# 5. Compile the LangGraph
workflow = StateGraph(AgentState)
workflow.add_node("llm_node", generate_medical_response)
workflow.add_node("safety_node", check_safety)

workflow.set_entry_point("llm_node")
workflow.add_edge("llm_node", "safety_node")
workflow.add_conditional_edges(
    "safety_node",
    route_safety,
    {
        "end": END,
        "rewrite": "llm_node"
    }
)
nexmed_agent = workflow.compile()


# 6. Update the Django View Controller
def chatbot_response(request):
    if request.method == 'POST':
        try:
            data = json.loads(request.body)
            user_message = data.get('message', '').strip()

            if not user_message:
                return JsonResponse({"response": "Please enter a valid message."})

            # 1. Initialize session chat history if not present
            if 'chat_history' not in request.session:
                request.session['chat_history'] = []

            # 2. Build initial state including session history
           # 2. Build initial state including session history
            initial_state = {
                "user_message": user_message,
                "chat_history": request.session['chat_history'],
                "ai_response": "", 
                "is_safe": True, 
                "loop_count": 0,
                # --- ADD THIS LINE ---
                "clinical_context": request.session.get('clinical_context', 'No scan results available yet.')
            }
            
            # 3. Execute the LangGraph workflow
            final_state = nexmed_agent.invoke(initial_state)
            
            # 4. Defensive check using .get() to prevent KeyError crashes
            is_safe = final_state.get("is_safe", True)
            ai_reply = final_state.get("ai_response", "").strip()

            if not is_safe:
                final_reply = "I apologize, but I cannot answer that safely. Please consult a licensed physician for medical advice."
            elif not ai_reply:
                final_reply = "NexMed AI was unable to generate a response. Please rephrase your query."
            else:
                final_reply = ai_reply

            # 5. Append this exchange to the session memory
            request.session['chat_history'].append({"role": "user", "content": user_message})
            request.session['chat_history'].append({"role": "assistant", "content": final_reply})

            # Keep only the last 10 messages (5 user/AI turns)
            request.session['chat_history'] = request.session['chat_history'][-10:]
            request.session.modified = True 

            # ==========================================
            # 6. FINAL PROJECT REQUIREMENT: AUDIT LOGGING
            # ==========================================
            # Save this exact interaction to the SQL database permanently
            try:
                ChatLog.objects.create(
                    user_message=user_message,
                    ai_response=final_reply
                )
            except Exception as db_error:
                print("🚨 DATABASE SAVE FAILED:", db_error)
            
            return JsonResponse({"response": final_reply})
            
        except Exception as e:
            print("🚨 GRAPH CRASH:", repr(e))
            return JsonResponse({"response": f"System Error: {str(e)}"})
            
    return JsonResponse({"error": "Invalid request"}, status=400)