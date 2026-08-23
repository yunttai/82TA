import django.db.models.deletion
import routing_api.models
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='EntityMapping',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('direction', models.CharField(blank=True, max_length=128, null=True)),
                ('score', models.DecimalField(decimal_places=6, max_digits=7)),
                ('grade', models.CharField(max_length=16)),
                ('signal_breakdown', models.JSONField()),
                ('algorithm_version', models.CharField(max_length=128)),
                ('valid_from', models.DateTimeField()),
                ('valid_to', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'entity_mapping',
            },
        ),
        migrations.CreateModel(
            name='IngestionSource',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code', models.CharField(max_length=128, unique=True)),
                ('data_type', models.CharField(max_length=64)),
                ('owner', models.CharField(max_length=255)),
            ],
            options={
                'db_table': 'ingestion_source',
            },
        ),
        migrations.CreateModel(
            name='ModelFamily',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('purpose', models.CharField(max_length=64, unique=True)),
                ('target_definition', models.TextField()),
                ('owner', models.CharField(max_length=255)),
            ],
            options={
                'db_table': 'model_family',
            },
        ),
        migrations.CreateModel(
            name='Provider',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('code', models.CharField(max_length=128, unique=True)),
                ('category', models.CharField(max_length=64)),
                ('enabled', models.BooleanField(default=True)),
                ('config_without_secret', models.JSONField(default=dict)),
                ('updated_at', models.DateTimeField()),
            ],
            options={
                'db_table': 'provider',
            },
        ),
        migrations.CreateModel(
            name='RouteCandidate',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('route_key', models.CharField(max_length=255)),
                ('pattern', models.CharField(max_length=64)),
                ('p50_seconds', models.IntegerField()),
                ('p90_seconds', models.IntegerField()),
                ('taxi_cost_expected', models.IntegerField()),
                ('taxi_cost_upper', models.IntegerField()),
                ('total_fare_expected', models.IntegerField()),
                ('walk_seconds', models.IntegerField()),
                ('transfer_count', models.IntegerField()),
                ('reliability_score', models.DecimalField(decimal_places=6, max_digits=7)),
                ('pareto', models.BooleanField()),
                ('reason_codes', models.JSONField()),
                ('warning_codes', models.JSONField()),
            ],
            options={
                'db_table': 'route_candidate',
            },
        ),
        migrations.CreateModel(
            name='BusVehicle',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('provider_vehicle_token', models.CharField(max_length=255, unique=True)),
                ('vehicle_type', models.CharField(blank=True, max_length=64, null=True)),
                ('first_seen_at', models.DateTimeField()),
                ('last_seen_at', models.DateTimeField()),
            ],
            options={
                'db_table': 'bus_vehicle',
                'constraints': [models.CheckConstraint(condition=models.Q(('last_seen_at__gte', models.F('first_seen_at'))), name='ck_vehicle_seen_order')],
            },
        ),
        migrations.CreateModel(
            name='MappingReview',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('status', models.CharField(max_length=32)),
                ('reviewer', models.CharField(blank=True, max_length=255, null=True)),
                ('note', models.TextField(blank=True, null=True)),
                ('reviewed_at', models.DateTimeField(blank=True, null=True)),
                ('entity_mapping', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.entitymapping')),
            ],
            options={
                'db_table': 'mapping_review',
            },
        ),
        migrations.CreateModel(
            name='ModelVersion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('version', models.CharField(max_length=128, unique=True)),
                ('status', models.CharField(max_length=32)),
                ('artifact_uri', models.CharField(max_length=1024)),
                ('artifact_sha256', models.CharField(max_length=64)),
                ('feature_schema_version', models.CharField(max_length=128)),
                ('training_scope', models.JSONField()),
                ('created_at', models.DateTimeField()),
                ('family', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.modelfamily')),
            ],
            options={
                'db_table': 'model_version',
            },
        ),
        migrations.CreateModel(
            name='ProviderEntity',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('entity_type', models.CharField(max_length=64)),
                ('external_id', models.CharField(max_length=255)),
                ('fingerprint', models.CharField(max_length=128)),
                ('normalized_identity', models.JSONField()),
                ('valid_from', models.DateTimeField()),
                ('valid_to', models.DateTimeField(blank=True, null=True)),
                ('provider', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.provider')),
            ],
            options={
                'db_table': 'provider_entity',
            },
        ),
        migrations.AddField(
            model_name='entitymapping',
            name='provider_entity',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.providerentity'),
        ),
        migrations.CreateModel(
            name='ProviderOperationState',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('operation', models.CharField(max_length=128)),
                ('documentation_state', models.CharField(max_length=32)),
                ('key_verification_state', models.CharField(max_length=32)),
                ('production_state', models.CharField(max_length=32)),
                ('health', models.CharField(max_length=32)),
                ('consecutive_failures', models.IntegerField(default=0)),
                ('checked_at', models.DateTimeField()),
                ('provider', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.provider')),
            ],
            options={
                'db_table': 'provider_operation_state',
            },
        ),
        migrations.CreateModel(
            name='RouteLeg',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('sequence', models.IntegerField()),
                ('mode', models.CharField(max_length=32)),
                ('expected_start_at', models.DateTimeField(blank=True, null=True)),
                ('expected_end_at', models.DateTimeField(blank=True, null=True)),
                ('p50_seconds', models.IntegerField()),
                ('p90_seconds', models.IntegerField()),
                ('fare_expected', models.IntegerField()),
                ('geometry', routing_api.models.GeographyField(blank=True, geometry_type='GEOMETRY', null=True, srid=4326)),
                ('provenance', models.JSONField()),
                ('candidate', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.routecandidate')),
            ],
            options={
                'db_table': 'route_leg',
            },
        ),
        migrations.CreateModel(
            name='RouteOptimizationRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('request_id', models.CharField(max_length=255, unique=True)),
                ('request_fingerprint', models.CharField(max_length=128)),
                ('origin', routing_api.models.GeographyField(geometry_type='POINT', srid=4326)),
                ('destination', routing_api.models.GeographyField(geometry_type='POINT', srid=4326)),
                ('departure_time', models.DateTimeField()),
                ('constraints', models.JSONField()),
                ('status', models.CharField(max_length=32)),
                ('ranking_policy_version', models.CharField(max_length=128)),
                ('duration_ms', models.IntegerField(blank=True, null=True)),
                ('provider_summary', models.JSONField(default=dict)),
                ('created_at', models.DateTimeField()),
                ('expires_at', models.DateTimeField()),
            ],
            options={
                'db_table': 'route_optimization_run',
                'constraints': [models.CheckConstraint(condition=models.Q(('duration_ms__isnull', True), ('duration_ms__gte', 0), _connector='OR'), name='ck_run_duration'), models.CheckConstraint(condition=models.Q(('expires_at__gt', models.F('created_at'))), name='ck_run_expiry')],
            },
        ),
        migrations.AddField(
            model_name='routecandidate',
            name='run',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.routeoptimizationrun'),
        ),
        migrations.CreateModel(
            name='TransferEvaluation',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('available_seconds', models.IntegerField()),
                ('required_seconds', models.IntegerField()),
                ('margin_p50_seconds', models.IntegerField()),
                ('margin_p90_seconds', models.IntegerField()),
                ('success_proxy', models.DecimalField(blank=True, decimal_places=6, max_digits=7, null=True)),
                ('reason_codes', models.JSONField()),
                ('route_leg', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.routeleg')),
            ],
            options={
                'db_table': 'transfer_evaluation',
            },
        ),
        migrations.CreateModel(
            name='TransportRoute',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canonical_name', models.CharField(max_length=255)),
                ('mode', models.CharField(max_length=32)),
                ('route_type', models.CharField(blank=True, max_length=64, null=True)),
                ('region', models.CharField(blank=True, max_length=128, null=True)),
                ('geometry', routing_api.models.GeographyField(blank=True, geometry_type='GEOMETRY', null=True, srid=4326)),
                ('valid_from', models.DateTimeField()),
                ('valid_to', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'transport_route',
                'constraints': [models.CheckConstraint(condition=models.Q(('valid_to__isnull', True), ('valid_to__gt', models.F('valid_from')), _connector='OR'), name='ck_route_valid_window')],
            },
        ),
        migrations.AddField(
            model_name='routeleg',
            name='route',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportroute'),
        ),
        migrations.AddField(
            model_name='entitymapping',
            name='transport_route',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportroute'),
        ),
        migrations.CreateModel(
            name='BusVehicleTrip',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('service_date', models.DateField()),
                ('direction', models.CharField(max_length=128)),
                ('inferred_start_at', models.DateTimeField()),
                ('inferred_end_at', models.DateTimeField(blank=True, null=True)),
                ('identity_version', models.CharField(max_length=128)),
                ('vehicle', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.busvehicle')),
                ('route', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportroute')),
            ],
            options={
                'db_table': 'bus_vehicle_trip',
            },
        ),
        migrations.CreateModel(
            name='TransportStop',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('canonical_name', models.CharField(max_length=255)),
                ('region', models.CharField(blank=True, max_length=128, null=True)),
                ('coordinate', routing_api.models.GeographyField(geometry_type='POINT', srid=4326)),
                ('attributes', models.JSONField(default=dict)),
                ('valid_from', models.DateTimeField()),
                ('valid_to', models.DateTimeField(blank=True, null=True)),
            ],
            options={
                'db_table': 'transport_stop',
                'constraints': [models.CheckConstraint(condition=models.Q(('valid_to__isnull', True), ('valid_to__gt', models.F('valid_from')), _connector='OR'), name='ck_stop_valid_window')],
            },
        ),
        migrations.CreateModel(
            name='RouteStop',
            fields=[
                ('pk', models.CompositePrimaryKey('route', 'sequence', 'direction', blank=True, editable=False, primary_key=True, serialize=False)),
                ('sequence', models.IntegerField()),
                ('direction', models.CharField(max_length=128)),
                ('cumulative_distance', models.DecimalField(blank=True, decimal_places=3, max_digits=14, null=True)),
                ('route', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.transportroute')),
                ('stop', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportstop')),
            ],
            options={
                'db_table': 'route_stop',
            },
        ),
        migrations.AddField(
            model_name='routeleg',
            name='from_stop',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='departing_route_legs', to='routing_api.transportstop'),
        ),
        migrations.AddField(
            model_name='routeleg',
            name='to_stop',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='arriving_route_legs', to='routing_api.transportstop'),
        ),
        migrations.AddField(
            model_name='entitymapping',
            name='transport_stop',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportstop'),
        ),
        migrations.CreateModel(
            name='BusLocationObservation',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('station_sequence', models.IntegerField(blank=True, null=True)),
                ('remaining_seats', models.IntegerField(blank=True, null=True)),
                ('crowded_code', models.IntegerField(blank=True, null=True)),
                ('coordinate', routing_api.models.GeographyField(blank=True, geometry_type='POINT', null=True, srid=4326)),
                ('observed_at', models.DateTimeField()),
                ('ingested_at', models.DateTimeField()),
                ('source', models.CharField(max_length=128)),
                ('quality_flags', models.JSONField(default=list)),
                ('trip', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.busvehicletrip')),
                ('stop', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportstop')),
            ],
            options={
                'db_table': 'bus_location_observation',
            },
        ),
        migrations.CreateModel(
            name='BusArrivalObservation',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('provider_eta_seconds', models.IntegerField(blank=True, null=True)),
                ('remaining_seats', models.IntegerField(blank=True, null=True)),
                ('observed_at', models.DateTimeField()),
                ('predicted_arrival_at', models.DateTimeField(blank=True, null=True)),
                ('ingested_at', models.DateTimeField()),
                ('source', models.CharField(max_length=128)),
                ('quality_flags', models.JSONField(default=list)),
                ('trip', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.busvehicletrip')),
                ('stop', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.transportstop')),
            ],
            options={
                'db_table': 'bus_arrival_observation',
            },
        ),
        migrations.CreateModel(
            name='VehicleCapacityAssertion',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('capacity', models.IntegerField()),
                ('source', models.CharField(max_length=128)),
                ('confidence', models.DecimalField(decimal_places=6, max_digits=7)),
                ('valid_from', models.DateTimeField()),
                ('valid_to', models.DateTimeField(blank=True, null=True)),
                ('vehicle', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.busvehicle')),
            ],
            options={
                'db_table': 'vehicle_capacity_assertion',
            },
        ),
        migrations.CreateModel(
            name='BusLegEnrichment',
            fields=[
                ('route_leg', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, primary_key=True, serialize=False, to='routing_api.routeleg')),
                ('expected_wait_seconds', models.IntegerField()),
                ('p90_wait_seconds', models.IntegerField()),
                ('boardability_proxy', models.DecimalField(blank=True, decimal_places=6, max_digits=7, null=True)),
                ('no_seat_probability', models.DecimalField(blank=True, decimal_places=6, max_digits=7, null=True)),
                ('coverage', models.CharField(max_length=32)),
                ('eta_model_version', models.CharField(blank=True, max_length=128, null=True)),
                ('seat_model_version', models.CharField(blank=True, max_length=128, null=True)),
                ('candidate_vehicles', models.JSONField()),
                ('entity_mapping', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, to='routing_api.entitymapping')),
            ],
            options={
                'db_table': 'bus_leg_enrichment',
            },
        ),
        migrations.CreateModel(
            name='IngestionCheckpoint',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('partition_key', models.CharField(max_length=255)),
                ('last_observed_at', models.DateTimeField(blank=True, null=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(max_length=32)),
                ('cursor', models.JSONField(default=dict)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.ingestionsource')),
            ],
            options={
                'db_table': 'ingestion_checkpoint',
                'constraints': [models.UniqueConstraint(fields=('source', 'partition_key'), name='uq_checkpoint_partition')],
            },
        ),
        migrations.CreateModel(
            name='DataQualityRun',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('dataset_version', models.CharField(max_length=128)),
                ('status', models.CharField(max_length=32)),
                ('metrics', models.JSONField()),
                ('violations', models.JSONField()),
                ('started_at', models.DateTimeField()),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('source', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.ingestionsource')),
            ],
            options={
                'db_table': 'data_quality_run',
                'constraints': [models.CheckConstraint(condition=models.Q(('finished_at__isnull', True), ('finished_at__gte', models.F('started_at')), _connector='OR'), name='ck_quality_run_order')],
            },
        ),
        migrations.CreateModel(
            name='ModelMetric',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('split_name', models.CharField(max_length=64)),
                ('slice_key', models.CharField(max_length=255)),
                ('metrics', models.JSONField()),
                ('evaluated_at', models.DateTimeField()),
                ('model_version', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='routing_api.modelversion')),
            ],
            options={
                'db_table': 'model_metric',
                'indexes': [models.Index(fields=['model_version', 'split_name', 'slice_key'], name='ix_model_metric_slice')],
            },
        ),
        migrations.CreateModel(
            name='ModelDeployment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('environment', models.CharField(max_length=32)),
                ('deployment_state', models.CharField(max_length=32)),
                ('traffic_fraction', models.DecimalField(decimal_places=6, max_digits=7)),
                ('activated_at', models.DateTimeField(blank=True, null=True)),
                ('deactivated_at', models.DateTimeField(blank=True, null=True)),
                ('model_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.modelversion')),
            ],
            options={
                'db_table': 'model_deployment',
                'indexes': [models.Index(fields=['environment', 'deployment_state'], name='ix_deployment_active')],
                'constraints': [models.CheckConstraint(condition=models.Q(('traffic_fraction__gte', 0), ('traffic_fraction__lte', 1)), name='ck_deployment_traffic'), models.CheckConstraint(condition=models.Q(('deactivated_at__isnull', True), ('activated_at__isnull', False), _connector='OR'), name='ck_deployment_activation_order')],
            },
        ),
        migrations.CreateModel(
            name='PredictionAudit',
            fields=[
                ('id', models.BigAutoField(primary_key=True, serialize=False)),
                ('request_id', models.CharField(max_length=255)),
                ('entity_key', models.CharField(max_length=255)),
                ('input_summary', models.JSONField()),
                ('prediction', models.JSONField()),
                ('created_at', models.DateTimeField()),
                ('model_version', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to='routing_api.modelversion')),
            ],
            options={
                'db_table': 'prediction_audit',
                'indexes': [models.Index(fields=['model_version', 'created_at'], name='ix_prediction_model_time')],
            },
        ),
        migrations.AddConstraint(
            model_name='providerentity',
            constraint=models.UniqueConstraint(fields=('provider', 'entity_type', 'external_id', 'valid_from'), name='uq_provider_entity_valid_from'),
        ),
        migrations.AddConstraint(
            model_name='providerentity',
            constraint=models.CheckConstraint(condition=models.Q(('valid_to__isnull', True), ('valid_to__gt', models.F('valid_from')), _connector='OR'), name='ck_provider_entity_window'),
        ),
        migrations.AddConstraint(
            model_name='provideroperationstate',
            constraint=models.UniqueConstraint(fields=('provider', 'operation'), name='uq_provider_operation'),
        ),
        migrations.AddConstraint(
            model_name='provideroperationstate',
            constraint=models.CheckConstraint(condition=models.Q(('consecutive_failures__gte', 0)), name='ck_provider_failures_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='routecandidate',
            constraint=models.UniqueConstraint(fields=('run', 'route_key'), name='uq_candidate_run_key'),
        ),
        migrations.AddConstraint(
            model_name='routecandidate',
            constraint=models.CheckConstraint(condition=models.Q(('p50_seconds__gte', 0), ('p90_seconds__gte', models.F('p50_seconds'))), name='ck_candidate_duration'),
        ),
        migrations.AddConstraint(
            model_name='routecandidate',
            constraint=models.CheckConstraint(condition=models.Q(('taxi_cost_expected__gte', 0), ('taxi_cost_upper__gte', models.F('taxi_cost_expected'))), name='ck_candidate_taxi_cost'),
        ),
        migrations.AddConstraint(
            model_name='routecandidate',
            constraint=models.CheckConstraint(condition=models.Q(('total_fare_expected__gte', 0), ('walk_seconds__gte', 0), ('transfer_count__gte', 0)), name='ck_candidate_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='routecandidate',
            constraint=models.CheckConstraint(condition=models.Q(('reliability_score__gte', 0), ('reliability_score__lte', 1)), name='ck_candidate_reliability'),
        ),
        migrations.AddConstraint(
            model_name='transferevaluation',
            constraint=models.CheckConstraint(condition=models.Q(('available_seconds__gte', 0), ('required_seconds__gte', 0)), name='ck_transfer_nonnegative'),
        ),
        migrations.AddConstraint(
            model_name='transferevaluation',
            constraint=models.CheckConstraint(condition=models.Q(('success_proxy__isnull', True), models.Q(('success_proxy__gte', 0), ('success_proxy__lte', 1)), _connector='OR'), name='ck_transfer_probability'),
        ),
        migrations.AddIndex(
            model_name='busvehicletrip',
            index=models.Index(fields=['route', 'service_date', 'direction'], name='ix_trip_identity'),
        ),
        migrations.AddConstraint(
            model_name='busvehicletrip',
            constraint=models.CheckConstraint(condition=models.Q(('inferred_end_at__isnull', True), ('inferred_end_at__gte', models.F('inferred_start_at')), _connector='OR'), name='ck_trip_time_order'),
        ),
        migrations.AddConstraint(
            model_name='routestop',
            constraint=models.CheckConstraint(condition=models.Q(('sequence__gte', 0)), name='ck_route_stop_sequence'),
        ),
        migrations.AddConstraint(
            model_name='routestop',
            constraint=models.CheckConstraint(condition=models.Q(('cumulative_distance__isnull', True), ('cumulative_distance__gte', 0), _connector='OR'), name='ck_route_stop_distance'),
        ),
        migrations.AddConstraint(
            model_name='routeleg',
            constraint=models.UniqueConstraint(fields=('candidate', 'sequence'), name='uq_leg_candidate_sequence'),
        ),
        migrations.AddConstraint(
            model_name='routeleg',
            constraint=models.CheckConstraint(condition=models.Q(('sequence__gte', 0)), name='ck_leg_sequence'),
        ),
        migrations.AddConstraint(
            model_name='routeleg',
            constraint=models.CheckConstraint(condition=models.Q(('p50_seconds__gte', 0), ('p90_seconds__gte', models.F('p50_seconds'))), name='ck_leg_duration'),
        ),
        migrations.AddConstraint(
            model_name='routeleg',
            constraint=models.CheckConstraint(condition=models.Q(('fare_expected__gte', 0)), name='ck_leg_fare'),
        ),
        migrations.AddConstraint(
            model_name='routeleg',
            constraint=models.CheckConstraint(condition=models.Q(('expected_start_at__isnull', True), ('expected_end_at__isnull', True), ('expected_end_at__gte', models.F('expected_start_at')), _connector='OR'), name='ck_leg_time_order'),
        ),
        migrations.AddIndex(
            model_name='entitymapping',
            index=models.Index(fields=['provider_entity', 'grade', 'valid_from'], name='ix_mapping_lookup'),
        ),
        migrations.AddConstraint(
            model_name='entitymapping',
            constraint=models.CheckConstraint(condition=models.Q(('score__gte', 0), ('score__lte', 1)), name='ck_mapping_score_probability'),
        ),
        migrations.AddConstraint(
            model_name='entitymapping',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('transport_route__isnull', False), ('transport_stop__isnull', True)), models.Q(('transport_route__isnull', True), ('transport_stop__isnull', False)), _connector='OR'), name='ck_mapping_one_target'),
        ),
        migrations.AddConstraint(
            model_name='entitymapping',
            constraint=models.CheckConstraint(condition=models.Q(('valid_to__isnull', True), ('valid_to__gt', models.F('valid_from')), _connector='OR'), name='ck_mapping_valid_window'),
        ),
        migrations.AddIndex(
            model_name='buslocationobservation',
            index=models.Index(fields=['trip', 'observed_at'], name='ix_location_trip_observed'),
        ),
        migrations.AddConstraint(
            model_name='buslocationobservation',
            constraint=models.CheckConstraint(condition=models.Q(('station_sequence__isnull', True), ('station_sequence__gte', 0), _connector='OR'), name='ck_location_sequence'),
        ),
        migrations.AddConstraint(
            model_name='buslocationobservation',
            constraint=models.CheckConstraint(condition=models.Q(('remaining_seats__isnull', True), ('remaining_seats__gte', 0), _connector='OR'), name='ck_location_seats'),
        ),
        migrations.AddConstraint(
            model_name='buslocationobservation',
            constraint=models.CheckConstraint(condition=models.Q(('ingested_at__gte', models.F('observed_at'))), name='ck_location_ingested_order'),
        ),
        migrations.AddIndex(
            model_name='busarrivalobservation',
            index=models.Index(fields=['stop', 'observed_at'], name='ix_arrival_stop_observed'),
        ),
        migrations.AddConstraint(
            model_name='busarrivalobservation',
            constraint=models.CheckConstraint(condition=models.Q(('provider_eta_seconds__isnull', True), ('provider_eta_seconds__gte', 0), _connector='OR'), name='ck_arrival_eta'),
        ),
        migrations.AddConstraint(
            model_name='busarrivalobservation',
            constraint=models.CheckConstraint(condition=models.Q(('remaining_seats__isnull', True), ('remaining_seats__gte', 0), _connector='OR'), name='ck_arrival_seats'),
        ),
        migrations.AddConstraint(
            model_name='busarrivalobservation',
            constraint=models.CheckConstraint(condition=models.Q(('ingested_at__gte', models.F('observed_at'))), name='ck_arrival_ingested_order'),
        ),
        migrations.AddConstraint(
            model_name='vehiclecapacityassertion',
            constraint=models.CheckConstraint(condition=models.Q(('capacity__gt', 0)), name='ck_capacity_positive'),
        ),
        migrations.AddConstraint(
            model_name='vehiclecapacityassertion',
            constraint=models.CheckConstraint(condition=models.Q(('confidence__gte', 0), ('confidence__lte', 1)), name='ck_capacity_confidence'),
        ),
        migrations.AddConstraint(
            model_name='vehiclecapacityassertion',
            constraint=models.CheckConstraint(condition=models.Q(('valid_to__isnull', True), ('valid_to__gt', models.F('valid_from')), _connector='OR'), name='ck_capacity_window'),
        ),
        migrations.AddConstraint(
            model_name='buslegenrichment',
            constraint=models.CheckConstraint(condition=models.Q(('expected_wait_seconds__gte', 0), ('p90_wait_seconds__gte', models.F('expected_wait_seconds'))), name='ck_bus_wait_order'),
        ),
        migrations.AddConstraint(
            model_name='buslegenrichment',
            constraint=models.CheckConstraint(condition=models.Q(('boardability_proxy__isnull', True), models.Q(('boardability_proxy__gte', 0), ('boardability_proxy__lte', 1)), _connector='OR'), name='ck_boardability_probability'),
        ),
        migrations.AddConstraint(
            model_name='buslegenrichment',
            constraint=models.CheckConstraint(condition=models.Q(('no_seat_probability__isnull', True), models.Q(('no_seat_probability__gte', 0), ('no_seat_probability__lte', 1)), _connector='OR'), name='ck_no_seat_probability'),
        ),
    ]
