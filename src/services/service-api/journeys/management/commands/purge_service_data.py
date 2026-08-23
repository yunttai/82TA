import json

from django.core.management.base import BaseCommand

from identity.lifecycle import purge_service_data


class Command(BaseCommand):
    help = "Purge Service-owned personal data after canonical retention windows."

    def handle(self, *args, **options):
        report = purge_service_data()
        self.stdout.write(json.dumps(report.to_dict(), sort_keys=True))
