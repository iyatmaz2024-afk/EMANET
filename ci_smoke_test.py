import os, tempfile, shutil
from pathlib import Path
import APK_Donusturucu_v6_1 as app

def log(x):
    print(x, flush=True)

java=app.detect_java()
sdk=app.detect_sdk()
if not java:
    raise SystemExit('JDK bulunamadı')
if app.java_major(java) != 17:
    raise SystemExit(f'JDK 17 gerekli, bulunan: {app.java_major(java)}')
if not sdk:
    raise SystemExit('Android SDK bulunamadı')
app.ensure_sdk(sdk, java, log)
gradle=app.ensure_gradle(log)
with tempfile.TemporaryDirectory() as td:
    td=Path(td)
    web=td/'web'; web.mkdir()
    (web/'index.html').write_text('<!doctype html><html><body><h1>APK Dönüştürücü CI Test</h1></body></html>', encoding='utf-8')
    project=td/'project'; project.mkdir()
    app.html_project(web, project, 'CI Test', 'com.example.citest', False, {'android.permission.INTERNET'}, version_name='1.0', version_code=1)
    env=os.environ.copy(); env['JAVA_HOME']=str(java); env['ANDROID_HOME']=str(sdk); env['ANDROID_SDK_ROOT']=str(sdk)
    code=app.run_build([str(gradle),'assembleDebug','--stacktrace'], project, env, log)
    if code:
        raise SystemExit('Gradle assembleDebug başarısız')
    apks=[p for p in project.rglob('*.apk') if 'outputs' in p.parts]
    if not apks:
        raise SystemExit('Gerçek APK çıktısı bulunamadı')
    apk=apks[0]
    if apk.stat().st_size < 10000:
        raise SystemExit('APK olağandışı küçük')
    print(f'SMOKE TEST PASS: {apk} ({apk.stat().st_size} bytes)')
