# Register your models here.
from django.contrib import admin
from .models import DiagnosticRecord

@admin.register(DiagnosticRecord)
class DiagnosticRecordAdmin(admin.ModelAdmin):
    list_display = ('patient_name', 'model_type', 'diagnosis_status', 'created_at')
    search_fields = ('patient_name', 'diagnosis_status')
    list_filter = ('model_type', 'created_at')