from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('routing_api', '0001_initial'),
    ]

    operations = [
        migrations.AddConstraint(
            model_name='modeldeployment',
            constraint=models.UniqueConstraint(condition=models.Q(('deactivated_at__isnull', True)), fields=('model_version', 'environment'), name='uq_deployment_current'),
        ),
    ]
