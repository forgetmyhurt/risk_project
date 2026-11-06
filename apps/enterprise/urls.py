from django.urls import path
from . import views

app_name = "enterprise"

urlpatterns = [
    path("enterprise/list/", views.enterprise_list, name="list"),
    path("enterprise/detail/<int:pk>/", views.enterprise_detail, name="detail"),
]