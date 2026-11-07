from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import Student


@admin.register(Student)
class StudentAdmin(UserAdmin):
    capacity = ('Личное хранилище', {'fields': ('quota_mib',)})
    fieldsets = (*UserAdmin.fieldsets, capacity)
    add_fieldsets = (*UserAdmin.add_fieldsets, capacity)
    list_display = ('username','email','quota_mib','is_active','is_staff')


admin.site.site_header = 'Polka · Управление хранилищем'
