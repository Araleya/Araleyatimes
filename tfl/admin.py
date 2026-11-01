from django.contrib import admin

from . import models


class BaseVersionAdmin(admin.ModelAdmin):
    list_display = ["version", "valid_from", "valid_to"]


class OperatorAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "agency", "base_version"]
    list_filter = ["base_version"]


admin.site.register(models.BaseVersion, BaseVersionAdmin)
admin.site.register(models.Operator, OperatorAdmin)
