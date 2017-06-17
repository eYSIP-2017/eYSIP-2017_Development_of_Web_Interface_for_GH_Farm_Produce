# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-17 14:45
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Alert',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('message', models.TextField()),
                ('timestamp', models.DateTimeField(default=django.utils.timezone.now)),
            ],
        ),
        migrations.CreateModel(
            name='Cart',
            fields=[
                ('cart_id', models.AutoField(primary_key=True, serialize=False)),
            ],
            options={
                'verbose_name_plural': 'cart',
            },
        ),
        migrations.CreateModel(
            name='Cart_session',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('cart_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Cart')),
            ],
            options={
                'verbose_name_plural': 'cart sessions',
            },
        ),
        migrations.CreateModel(
            name='Crop',
            fields=[
                ('crop_id', models.AutoField(primary_key=True, serialize=False)),
                ('local_name', models.CharField(max_length=100, null=True)),
                ('english_name', models.CharField(max_length=100, null=True)),
                ('short_name', models.CharField(default='Unknown', max_length=11)),
                ('scientific_name', models.CharField(max_length=100, null=True)),
                ('shelf_life', models.FloatField()),
                ('imagepath', models.CharField(max_length=100, null=True)),
                ('availability', models.FloatField(default=0)),
                ('price', models.FloatField()),
            ],
            options={
                'verbose_name_plural': 'crops',
            },
        ),
        migrations.CreateModel(
            name='Inventory',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weight', models.FloatField()),
                ('sold', models.FloatField(default=0)),
                ('minimum', models.FloatField(default=0)),
                ('maximum', models.FloatField(default=0)),
                ('crop_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Crop')),
            ],
            options={
                'verbose_name_plural': 'inventories',
            },
        ),
        migrations.CreateModel(
            name='Machine',
            fields=[
                ('machine_id', models.AutoField(primary_key=True, serialize=False)),
                ('password', models.CharField(max_length=20)),
                ('location', models.CharField(max_length=255)),
                ('date_of_manufacture', models.DateTimeField()),
                ('version', models.CharField(max_length=20)),
                ('last_login', models.DateTimeField()),
            ],
            options={
                'verbose_name_plural': 'machines',
            },
        ),
        migrations.CreateModel(
            name='Order',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('weight', models.FloatField(default=0)),
                ('time', models.DateTimeField(default=django.utils.timezone.now)),
                ('delivery_date', models.DateTimeField(blank=True, null=True)),
                ('status', models.CharField(default='pending', max_length=20)),
                ('cart_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Cart')),
                ('crop_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Crop')),
            ],
            options={
                'verbose_name_plural': 'orders',
            },
        ),
        migrations.CreateModel(
            name='Produce',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('image', models.CharField(max_length=255)),
                ('weight', models.FloatField()),
                ('timestamp', models.DateTimeField()),
                ('date_of_produce', models.DateTimeField()),
                ('date_of_expiry', models.DateTimeField()),
                ('status', models.FloatField()),
                ('crop_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Crop')),
                ('machine_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Machine')),
            ],
            options={
                'verbose_name_plural': 'produce',
            },
        ),
        migrations.CreateModel(
            name='Trough',
            fields=[
                ('trough_id', models.AutoField(primary_key=True, serialize=False)),
                ('machine_id', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Machine')),
            ],
            options={
                'verbose_name_plural': 'troughs',
            },
        ),
        migrations.CreateModel(
            name='User',
            fields=[
                ('user_id', models.AutoField(primary_key=True, serialize=False)),
                ('email', models.EmailField(max_length=254)),
                ('first_name', models.CharField(max_length=100, null=True)),
                ('last_name', models.CharField(max_length=100, null=True)),
                ('password', models.CharField(max_length=20)),
                ('address_line1', models.CharField(max_length=100)),
                ('address_line2', models.CharField(max_length=100, null=True)),
                ('state', models.CharField(max_length=100)),
                ('country', models.CharField(max_length=100)),
                ('pin_code', models.CharField(max_length=20)),
                ('user_type', models.CharField(max_length=20)),
                ('contact', models.TextField()),
                ('last_cart', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='farmapp.Cart')),
            ],
            options={
                'verbose_name_plural': 'users',
            },
        ),
        migrations.AddField(
            model_name='produce',
            name='trough_id',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Trough'),
        ),
        migrations.AddField(
            model_name='order',
            name='seller',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='Producer', to='farmapp.User'),
        ),
        migrations.AddField(
            model_name='order',
            name='user_id',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='Consumer', to='farmapp.User'),
        ),
        migrations.AddField(
            model_name='machine',
            name='user_id',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.CASCADE, to='farmapp.User'),
        ),
        migrations.AddField(
            model_name='inventory',
            name='user_id',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.User'),
        ),
        migrations.AddField(
            model_name='cart_session',
            name='crop_id',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.Crop'),
        ),
        migrations.AddField(
            model_name='alert',
            name='user_id',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, to='farmapp.User'),
        ),
    ]
