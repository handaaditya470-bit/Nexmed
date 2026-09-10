import os
import cv2
import numpy as np
import tensorflow as tf
from django.shortcuts import render
from django.core.files.storage import FileSystemStorage
from django.conf import settings
from tensorflow.keras.applications.densenet import preprocess_input

# 1. IMPORT YOUR NEW DATABASE MODEL HERE
from .models import DiagnosticRecord 

# Import blood report script
from .blood_processor import extract_blood_data


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

# INFERENCE LOGIC
def run_pneumonia_inference(image_path):
    model = load_keras_model('pneumonia', PNEUMONIA_MODEL_PATH)
    if not model:
        return {"diagnosis": "Error", "details": "Pneumonia model file not found in models/"}
    
    # Example preprocessing (adjust image size to match your training set)
    img = tf.keras.utils.load_img(image_path, target_size=(224, 224))
    img_array = tf.keras.utils.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    prediction = model.predict(img_array)[0][0]
    result = "Pneumonia Detected" if prediction > 0.5 else "Normal (No Pneumonia)"
    confidence = f"{prediction * 100:.2f}%" if prediction > 0.5 else f"{(1 - prediction) * 100:.2f}%"

    return {"diagnosis": result, "confidence": confidence}


def run_ecg_inference(image_path):
    model = load_keras_model('ecg', ECG_MODEL_PATH)
    if not model:
        return {"diagnosis": "Error", "details": "ECG model file missing in models/"}
    
    # 1. LOAD IMAGE
    img = tf.keras.utils.load_img(image_path, target_size=(512, 512))
    
    # 2. DO NOT DIVIDE BY 255. Use DenseNet's official preprocessor.
    img_array = tf.keras.utils.img_to_array(img)
    img_array = np.expand_dims(img_array, axis=0)
    processed_img = preprocess_input(img_array)

    # 3. Predict
    raw_preds = model.predict(processed_img)[0]
    
    # 4. ALPHABETICAL NODE ORDER
    class_labels = ['NORM', 'MI', 'STTC', 'CD', 'HYP']
    
    # Pair the labels with the predictions and sort them highest to lowest
    results = list(zip(class_labels, raw_preds))
    results.sort(key=lambda x: x[1], reverse=True)

    threshold = 0.5
    report_lines = []
    detected_diagnoses = []

    report_lines.append("MULTI-LABEL ECG DIAGNOSTIC REPORT")
    report_lines.append("-" * 45)

    # Loop through the sorted results to build the terminal-style report
    for label, prob in results:
        percentage = prob * 100
        status = "POSITIVE" if prob >= threshold else "Negative"
        
        if status == "POSITIVE" and label != "NORM":
            detected_diagnoses.append(label)
            
        report_lines.append(f"** {label:<4} : {percentage:>6.2f}%  --> {status}")

    report_lines.append("-" * 45)
    
    if detected_diagnoses:
        diagnoses_str = ", ".join(detected_diagnoses)
    else:
        is_normal = next((prob for lbl, prob in results if lbl == "NORM"), 0) >= threshold
        diagnoses_str = "NORM (Normal)" if is_normal else "None Detected (All below 50%)"

    report_lines.append(f"🚨 DIAGNOSES DETECTED: {diagnoses_str}")

    return {
        "diagnosis": f"DIAGNOSES DETECTED: {diagnoses_str}",
        "details": "\n".join(report_lines)
    }

def run_kidney_inference(image_path):
    model = load_keras_model('kidney', KIDNEY_MODEL_PATH)
    if not model:
        return {"diagnosis": "Error", "details": "Kidney stone model file missing in models/"}
    
    # Preprocess CT scan/X-ray image
    img = tf.keras.utils.load_img(image_path, target_size=(224, 224))
    img_array = tf.keras.utils.img_to_array(img) / 255.0
    img_array = np.expand_dims(img_array, axis=0)

    prediction = model.predict(img_array)[0][0]
    result = "Kidney Stone Detected" if prediction > 0.5 else "No Kidney Stone Detected"
    confidence = f"{prediction * 100:.2f}%" if prediction > 0.5 else f"{(1 - prediction) * 100:.2f}%"

    return {"diagnosis": result, "confidence": confidence}


# 2. UPDATED VIEW CONTROLLER
def index(request):
    result = None
    uploaded_file_url = None

    if request.method == 'POST' and request.FILES.get('medical_image'):
        model_type = request.POST.get('model_type')
        uploaded_file = request.FILES['medical_image']
        
        # Grab the new patient details from the HTML form
        p_name = request.POST.get('patient_name', 'Unknown Patient')
        p_age = request.POST.get('patient_age') or None
        p_sex = request.POST.get('patient_sex', 'Not Specified')

        # Save the initial record and image directly to the database
        record = DiagnosticRecord.objects.create(
            patient_name=p_name,
            patient_age=p_age,
            patient_sex=p_sex,
            model_type=model_type,
            image=uploaded_file
        )

        # Get the physical file path for the AI models to read from the database object
        file_path = record.image.path
        uploaded_file_url = record.image.url

        # Run AI Inference
        if model_type == 'pneumonia':
            result = run_pneumonia_inference(file_path)
        elif model_type == 'ecg':
            result = run_ecg_inference(file_path)
        elif model_type == 'kidney':
            result = run_kidney_inference(file_path)
        elif model_type == 'blood_report':
            result = extract_blood_data(file_path)

        # Update the database record with the final AI results
        if result:
            record.diagnosis_status = result.get('diagnosis', 'Error')
            record.detailed_report = result.get('details', '')
            record.save()

    return render(request, 'diagnostics/index.html', {
        'result': result,
        'uploaded_file_url': uploaded_file_url
    })