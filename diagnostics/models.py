from django.db import models
from django.db import models
from django.contrib.auth.models import User

class ChatLog(models.Model):
    # If users don't log in, you can remove the user field
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    user_message = models.TextField()
    ai_response = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Log: {self.timestamp.strftime('%Y-%m-%d %H:%M')}"
    
class DiagnosticRecord(models.Model):
    patient_name = models.CharField(max_length=150, blank=True, null=True)
    patient_age = models.IntegerField(blank=True, null=True)
    patient_sex = models.CharField(max_length=10, blank=True, null=True)
    model_type = models.CharField(max_length=50)
    
    # Django will automatically save the uploaded file to your MEDIA_ROOT/scans/ folder
    image = models.ImageField(upload_to='scans/')
    
    # AI Results
    diagnosis_status = models.CharField(max_length=255, blank=True)
    detailed_report = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.patient_name} | {self.model_type} ({self.created_at.strftime('%Y-%m-%d')})"
# Create your models here.
