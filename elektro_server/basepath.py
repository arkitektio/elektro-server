from django.urls import path, include, re_path
from django.conf import settings

def basepath(rel_path, *args, **kwargs):
    if settings.MY_SCRIPT_NAME:
        return path(settings.MY_SCRIPT_NAME.lstrip("/") + "/" + rel_path, *args, **kwargs)
    else: 
        return path(rel_path, *args, **kwargs)
    
def re_basepath(rel_path, *args, **kwargs):
    if settings.MY_SCRIPT_NAME:
        return re_path(fr"^{settings.MY_SCRIPT_NAME.lstrip('/')}/" + rel_path, *args, **kwargs)
    else: 
        return re_path(rel_path, *args, **kwargs)