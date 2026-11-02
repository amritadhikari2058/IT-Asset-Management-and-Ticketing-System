path = 'D:\\IT-Asset-Management-and-Ticketing-System\\backend\\config\\urls.py'
with open(path, 'a') as f:
    f.write('\n\nfrom common import health\nurlpatterns += [\n    path("health/", health.health, name="health"),\n    path("ready/", health.ready, name="ready"),\n]\n')
