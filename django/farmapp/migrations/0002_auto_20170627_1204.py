# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-27 12:04
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('farmapp', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='alert',
            name='type',
            field=models.CharField(default='unknown', max_length=20),
        ),
        migrations.AlterField(
            model_name='user',
            name='contact',
            field=models.CharField(max_length=15),
        ),
    ]
