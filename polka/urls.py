from django.contrib import admin
from django.contrib.auth.views import LoginView, LogoutView
from django.urls import path
from locker import pages

urlpatterns = [
    path('', pages.files), path('change/', pages.change), path('download/', pages.download),
    path('stats/', pages.stats), path('login/', LoginView.as_view()), path('logout/', LogoutView.as_view()),
    path('admin/', admin.site.urls),
]
