"""
URL configuration for elektro_server project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/4.2/topics/http/urls/
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
from django.urls import path, include
from strawberry.django.views import AsyncGraphQLView
from kante.path import dynamicpath

from health_check.views import HealthCheckView
from django.views.decorators.csrf import csrf_exempt
from arkitekt_service.service.views import answers_challenge
from elektro_server.hook_agent import agent as hook_agent
from elektro_server.service import service as rekuest_service


x = "s"

urlpatterns = [
    dynamicpath("admin/", admin.site.urls),
    dynamicpath("ht", answers_challenge(csrf_exempt(HealthCheckView.as_view(checks=["health_check.Database"]))), name="health_check"),
    # What this service hosts and emits, read by the hub's rekuest (internal network only).
    *rekuest_service.urls,
    # This process's hook agent: the hub's rekuest POSTs it Assigns (internal network only). Not the service's.
    *hook_agent.urls,
]
