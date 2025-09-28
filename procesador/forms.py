from django import forms

class UploadExcelForm(forms.Form):
    archivo = forms.FileField(label="Subir Excel")


class UploadZipForm(forms.Form):
    archivo = forms.FileField(label="Subir ZIP de XML")
