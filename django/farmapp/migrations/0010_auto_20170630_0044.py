# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-30 00:44
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farmapp', '0009_auto_20170630_0032'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='user_type',
            field=models.CharField(choices=[('Producer', 'Producer'), ('Consumer', 'Consumer')], default='Consumer', max_length=20),
        ),
    ]
