from django.contrib import admin

# Register your models here.
from core import models
from simple_history.admin import SimpleHistoryAdmin


class HistoryAdmin(SimpleHistoryAdmin):
    list_display = ["id"]
    history_list_display = ["name", "user"]
    search_fields = ["name", "user__username"]


admin.site.register(models.Trace, HistoryAdmin)
admin.site.register(models.Instrument)
admin.site.register(models.Dataset, HistoryAdmin)
admin.site.register(models.ROI)
admin.site.register(models.ZarrStore)
admin.site.register(models.S3Store)
