from django.urls import path
from . import views

app_name = 'drive'
urlpatterns = [
    path('statistics/', views.statistics, name='statistics'),
    path('', views.browse, name='index'),
    path('upload/', views.upload, name='upload'),
    path('folder/', views.create_folder, name='folder'),
    path('rename/', views.rename, name='rename'),
    path('delete/', views.delete, name='delete'),
    path('download/', views.download, name='download'),
]
