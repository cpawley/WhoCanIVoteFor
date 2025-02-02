from django.contrib.sitemaps import Sitemap
from .models import Person


class PersonSitemap(Sitemap):
    changefreq = "daily"
    priority = 0.9
    protocol = "https"

    def items(self):
        return Person.objects.all().order_by("pk")
