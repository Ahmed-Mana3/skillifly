from django.db import migrations


def _existing_columns(connection, table_name):
    vendor = connection.vendor
    with connection.cursor() as cursor:
        if vendor == "sqlite":
            cursor.execute(f"PRAGMA table_info({table_name})")
            return {row[1] for row in cursor.fetchall()}

        if vendor == "postgresql":
            cursor.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = %s
                """,
                [table_name],
            )
            return {row[0] for row in cursor.fetchall()}

        # Fallback for other DB engines.
        cursor.execute(f"SELECT * FROM {table_name} LIMIT 0")
        return {col[0] for col in cursor.description}


def repair_userpayment_kashier_columns(apps, schema_editor):
    table_name = "core_userpayment"
    existing = _existing_columns(schema_editor.connection, table_name)

    if "kashier_order_id" not in existing:
        schema_editor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN kashier_order_id varchar(255) NULL"
        )

    if "kashier_session_id" not in existing:
        schema_editor.execute(
            f"ALTER TABLE {table_name} ADD COLUMN kashier_session_id varchar(255) NULL"
        )


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0030_profile_section_order"),
    ]

    operations = [
        migrations.RunPython(
            repair_userpayment_kashier_columns, migrations.RunPython.noop
        ),
    ]
