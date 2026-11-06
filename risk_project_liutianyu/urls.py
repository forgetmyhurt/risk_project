"""
URL configuration for risk_project_liutianyu project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.2/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""

from django.contrib import admin
from django.urls import include
from django.urls import path
from apps.enterprise import views as ent_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", ent_views.index, name="index"),
    path("", include("apps.enterprise.urls")),
    path("", include("apps.accounts.urls")),
    path("", include("apps.risk.urls")),
    path("", include("apps.manager.urls")),
    path("", include("apps.dashboard.urls")),
    path("", include("apps.ai.urls")),
]
