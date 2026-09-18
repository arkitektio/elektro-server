from django.contrib import admin

# Register your models here.
from core import models
from simple_history.admin import SimpleHistoryAdmin


class HistoryAdmin(SimpleHistoryAdmin):
    list_display = ["id"]
    history_list_display = ["name", "user"]
    search_fields = ["name", "user__username"]


admin.site.register(models.ArrayDataset, HistoryAdmin)
admin.site.register(models.DataArray)
admin.site.register(models.Folder, HistoryAdmin)
admin.site.register(models.AnnotationCollection)
admin.site.register(models.Annotation)
