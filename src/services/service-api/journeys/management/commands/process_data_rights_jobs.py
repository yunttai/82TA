import json

from django.core.management.base import BaseCommand, CommandError

from identity.data_rights_worker import process_data_rights_jobs


class Command(BaseCommand):
    help = "Process bounded pending Service data export/deletion jobs."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        try:
            report = process_data_rights_jobs(limit=options["limit"])
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report.to_dict(), sort_keys=True))
