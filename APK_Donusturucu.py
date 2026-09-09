from __future__ import annotations
import os, re, shutil, subprocess, threading, time, zipfile, urllib.request
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

APP='APK Donusturucu'
VERSION='5.0'
GRADLE='9.6.0'
AGP='9.4.0'
SDK_API=37
BUILD_TOOLS='36.0.0'
HOME=Path.home()
ROOT=HOME/'APKDonusturucu'
CACHE=ROOT/'cache'
BUILDS=ROOT/'builds'
OUTPUTS=ROOT/'outputs'
for p in (CACHE,BUILDS,OUTPUTS): p.mkdir(parents=True,exist_ok=True)

def safe_extract(src:Path,dst:Path):
    dst=dst.resolve()
    with zipfile.ZipFile(src) as z:
        for m in z.infolist():
            target=(dst/m.filename).resolve()
            if os.path.commonpath([str(dst),str(target)])!=str(dst): raise RuntimeError('Guvenli olmayan ZIP yolu bulundu.')
        z.extractall(dst)

def detect_java():
    c=[]
    if os.getenv('JAVA_HOME'): c.append(Path(os.environ['JAVA_HOME']))
    pf=Path(os.getenv('ProgramFiles',r'C:\Program Files'))
    c += [pf/'Android'/'Android Studio'/'jbr',pf/'Microsoft'/'jdk-17']
    for x in c:
        if (x/'bin'/'java.exe').exists(): return x
    j=shutil.which('java')
    return Path(j).resolve().parent.parent if j else None

def detect_sdk():
    for k in ('ANDROID_HOME','ANDROID_SDK_ROOT'):
        v=os.getenv(k)
        if v and Path(v).exists(): return Path(v)
    p=Path(os.getenv('LOCALAPPDATA',''))/'Android'/'Sdk'
    return p if p.exists() else None

def find_root(p:Path):
    if (p/'settings.gradle').exists() or (p/'settings.gradle.kts').exists(): return p
    for f in p.rglob('settings.gradle*'):
        if len(f.relative_to(p).parts)<=5: return f.parent
    return None

def ensure_gradle(log):
    home=CACHE/f'gradle-{GRADLE}'
    exe=home/'bin'/'gradle.bat'
    if exe.exists(): return exe
    sysg=shutil.which('gradle')
    if sysg: return Path(sysg)
    zp=CACHE/f'gradle-{GRADLE}-bin.zip'
    log(f'Gradle {GRADLE} indiriliyor...')
    urllib.request.urlretrieve(f'https://services.gradle.org/distributions/gradle-{GRADLE}-bin.zip',zp)
    with zipfile.ZipFile(zp) as z: z.extractall(CACHE)
    if not exe.exists(): raise RuntimeError('Gradle kurulamadı.')
    return exe

def html_project(src:Path,project:Path,name:str,pkg:str,http:bool):
    app=project/'app'; assets=app/'src'/'main'/'assets'/'www'; values=app/'src'/'main'/'res'/'values'; java=app/'src'/'main'/'java'/Path(*pkg.split('.'))
    assets.mkdir(parents=True); values.mkdir(parents=True); java.mkdir(parents=True)
    if src.is_file() and src.suffix.lower() in ('.html','.htm'):
        shutil.copy2(src,assets/'index.html')
        for x in src.parent.iterdir():
            if x!=src and x.is_file() and x.suffix.lower() in {'.css','.js','.png','.jpg','.jpeg','.svg','.webp','.json','.mp3','.mp4','.woff','.woff2','.ttf'}: shutil.copy2(x,assets/x.name)
    else:
        temp=project/'websrc'; temp.mkdir()
        if src.is_file(): safe_extract(src,temp)
        else: shutil.copytree(src,temp,dirs_exist_ok=True)
        indexes=list(temp.rglob('index.html'))
        if not indexes: raise RuntimeError('HTML paketi icinde index.html bulunamadı.')
        shutil.copytree(indexes[0].parent,assets,dirs_exist_ok=True)
        shutil.rmtree(temp,ignore_errors=True)
    (project/'settings.gradle').write_text("pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name='APKApp'\ninclude ':app'\n",encoding='utf-8')
    (project/'build.gradle').write_text(f"plugins {{ id 'com.android.application' version '{AGP}' apply false }}\n",encoding='utf-8')
    (project/'gradle.properties').write_text('org.gradle.jvmargs=-Xmx2048m -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\n',encoding='utf-8')
    (app/'build.gradle').write_text(f"plugins {{ id 'com.android.application' }}\nandroid {{ namespace '{pkg}'; compileSdk {SDK_API}; defaultConfig {{ applicationId '{pkg}'; minSdk 23; targetSdk {SDK_API}; versionCode 1; versionName '1.0' }} }}\n",encoding='utf-8')
    clear='true' if http else 'false'
    manifest=f'''<manifest xmlns:android="http://schemas.android.com/apk/res/android"><uses-permission android:name="android.permission.INTERNET"/><application android:theme="@style/AppTheme" android:label="@string/app_name" android:usesCleartextTraffic="{clear}"><activity android:name=".MainActivity" android:exported="true"><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'''
    (app/'src'/'main'/'AndroidManifest.xml').write_text(manifest,encoding='utf-8')
    safe_name=name.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
    (values/'strings.xml').write_text(f'<resources><string name="app_name">{safe_name}</string></resources>',encoding='utf-8')
    (values/'styles.xml').write_text('<resources><style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar"/></resources>',encoding='utf-8')
    activity=f'''package {pkg};\nimport android.app.Activity;\nimport android.os.Bundle;\nimport android.webkit.WebView;\nimport android.webkit.WebViewClient;\npublic class MainActivity extends Activity {{ private WebView w; public void onCreate(Bundle b){{super.onCreate(b);w=new WebView(this);setContentView(w);w.getSettings().setJavaScriptEnabled(true);w.getSettings().setDomStorageEnabled(true);w.setWebViewClient(new WebViewClient());w.loadUrl("file:///android_asset/www/index.html");}} @Override public void onBackPressed(){{if(w.canGoBack())w.goBack();else super.onBackPressed();}} }}'''
    (java/'MainActivity.java').write_text(activity,encoding='utf-8')

def run_build(cmd,cwd,env,log):
    p=subprocess.Popen(cmd,cwd=str(cwd),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    for line in p.stdout: log(line.rstrip())
    return p.wait()

class App(tk.Tk):
    def __init__(self):
        super().__init__(); self.title(f'{APP} {VERSION}'); self.geometry('900x650'); self.src=tk.StringVar(); self.name=tk.StringVar(value='Uygulamam'); self.pkg=tk.StringVar(value='com.apkkurucu.uygulamam'); self.http=tk.BooleanVar(); self.release=tk.BooleanVar(); self.make()
    def make(self):
        f=ttk.Frame(self,padding=16); f.pack(fill='both',expand=True); ttk.Label(f,text='APK Dönüştürücü',font=('Segoe UI',22,'bold')).pack(anchor='w'); ttk.Label(f,text='HTML / HTML ZIP / Android proje ZIP veya klasörü → APK').pack(anchor='w',pady=(0,12))
        r=ttk.Frame(f); r.pack(fill='x'); ttk.Entry(r,textvariable=self.src).pack(side='left',fill='x',expand=True); ttk.Button(r,text='Dosya Seç',command=self.file).pack(side='left',padx=5); ttk.Button(r,text='Klasör Seç',command=self.folder).pack(side='left')
        a=ttk.LabelFrame(f,text='Ayarlar',padding=10); a.pack(fill='x',pady=10); ttk.Label(a,text='Uygulama adı').grid(row=0,column=0,sticky='w'); ttk.Entry(a,textvariable=self.name).grid(row=0,column=1,sticky='ew',padx=8); ttk.Label(a,text='Paket adı').grid(row=1,column=0,sticky='w'); ttk.Entry(a,textvariable=self.pkg).grid(row=1,column=1,sticky='ew',padx=8); ttk.Checkbutton(a,text='HTTP bağlantılarına izin ver',variable=self.http).grid(row=2,column=1,sticky='w'); ttk.Checkbutton(a,text='Release APK',variable=self.release).grid(row=3,column=1,sticky='w'); a.columnconfigure(1,weight=1)
        b=ttk.Frame(f); b.pack(fill='x'); ttk.Button(b,text='APK OLUŞTUR',command=self.start).pack(side='left'); ttk.Button(b,text='Sistem Kontrolü',command=self.check).pack(side='left',padx=6); ttk.Button(b,text='Çıktılar',command=lambda:os.startfile(OUTPUTS)).pack(side='left')
        self.status=ttk.Label(f,text='Hazır'); self.status.pack(anchor='w',pady=8); self.logbox=tk.Text(f,font=('Consolas',9)); self.logbox.pack(fill='both',expand=True)
    def file(self):
        p=filedialog.askopenfilename(filetypes=[('Desteklenen','*.html *.htm *.zip'),('Tümü','*.*')]);
        if p:self.src.set(p);self.name.set(Path(p).stem)
    def folder(self):
        p=filedialog.askdirectory();
        if p:self.src.set(p);self.name.set(Path(p).name)
    def log(self,s): self.after(0,lambda:(self.logbox.insert('end',s+'\n'),self.logbox.see('end')))
    def check(self): messagebox.showinfo('Sistem',f'JDK: {detect_java() or "YOK"}\nAndroid SDK: {detect_sdk() or "YOK"}')
    def start(self): threading.Thread(target=self.worker,daemon=True).start()
    def worker(self):
        try:
            src=Path(self.src.get().strip());
            if not src.exists(): raise RuntimeError('Kaynak dosya/klasör seçilmedi.')
            java=detect_java(); sdk=detect_sdk()
            if not java: raise RuntimeError('JDK bulunamadı. Android Studio veya JDK 17 kurun.')
            if not sdk: raise RuntimeError('Android SDK bulunamadı. Android Studio SDK Manager ile kurun.')
            gradle=ensure_gradle(self.log); stamp=time.strftime('%Y%m%d_%H%M%S'); project=BUILDS/f'build_{stamp}'; project.mkdir(); root=None
            if src.is_dir() and find_root(src): shutil.copytree(src,project,dirs_exist_ok=True); root=find_root(project)
            elif src.suffix.lower()=='.zip':
                probe=project/'probe'; probe.mkdir(); safe_extract(src,probe); ar=find_root(probe)
                if ar: root=ar
                else: shutil.rmtree(probe); html_project(src,project,self.name.get(),re.sub('[^a-z0-9_.]','',self.pkg.get().lower()),self.http.get()); root=project
            else: html_project(src,project,self.name.get(),re.sub('[^a-z0-9_.]','',self.pkg.get().lower()),self.http.get()); root=project
            env=os.environ.copy(); env['JAVA_HOME']=str(java); env['ANDROID_HOME']=str(sdk); env['ANDROID_SDK_ROOT']=str(sdk)
            wrapper=root/'gradlew.bat'; exe=wrapper if wrapper.exists() else gradle; task='assembleRelease' if self.release.get() else 'assembleDebug'; self.log(f'Derleniyor: {task}')
            code=run_build([str(exe),task,'--stacktrace'],root,env,self.log)
            if code: raise RuntimeError('Gradle derlemesi başarısız. Günlüğü kontrol edin.')
            apks=list(root.rglob('*.apk'))
            if not apks: raise RuntimeError('APK bulunamadı.')
            out=OUTPUTS/f'APK_{stamp}'; out.mkdir(); copied=[]
            for x in apks:
                if 'outputs' in x.parts: d=out/x.name; shutil.copy2(x,d); copied.append(d)
            messagebox.showinfo('Tamamlandı','APK hazır:\n'+'\n'.join(map(str,copied)))
        except Exception as e: self.log('HATA: '+str(e)); messagebox.showerror('Hata',str(e))

if __name__=='__main__': App().mainloop()
