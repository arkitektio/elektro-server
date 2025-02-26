from django.core.management.base import BaseCommand
from django.conf import settings
from core.duck import DuckLayer
import json
import omegaconf


class Command(BaseCommand):
    help = "Creates all configured apps or overwrites them"

    def handle(self, *args, **options):

        d = DuckLayer()
        d.connection.install_extension("httpfs")
       
        

        









        
