from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from .models import StorageQuota

class QuotaInline(admin.StackedInline):
    model = StorageQuota
    can_delete = False
    extra = 0
    max_num = 1

User = get_user_model()
admin.site.unregister(User)
@admin.register(User)
class PolkaUserAdmin(UserAdmin):
    inlines = (QuotaInline,)

@admin.register(StorageQuota)
class StorageQuotaAdmin(admin.ModelAdmin):
    list_display = ('user', 'quota_mb')
    list_select_related = ('user',)
    search_fields = ('user__username',)
