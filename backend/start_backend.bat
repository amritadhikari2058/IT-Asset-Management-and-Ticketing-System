@echo off
cd /d "E:\OneDrive\Desktop\Ticket and Asset Management System\backend"
python manage.py runserver 0:8000 >..\backend.log 2>&1
echo Backend started on port 8000