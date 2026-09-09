from __future__ import annotations
import os, re, shutil, subprocess, threading, time, zipfile, urllib.request, json, hashlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox, simpledialog

APP="APK Dönüştürücü Pro"
VERSION="6.0"
GRADLE="9.6.0"
AGP="9.4.0"
SDK_API=37
BUILD_TOOLS="36.0.0"

HOME=Path.home()
ROOT=HOME/"APKDonusturucuPro"
CACHE=ROOT/"cache"
BUILDS=ROOT/"builds"
OUTPUTS=ROOT/"outputs"
PROFILES=ROOT/"profiles"
for p in (CACHE,BUILDS,OUTPUTS,PROFILES): p.mkdir(parents=True,exist_ok=True)

PERMISSIONS = {
    "İnternet":"android.permission.INTERNET",
    "Kamera":"android.permission.CAMERA",
    "Mikrofon":"android.permission.RECORD_AUDIO",
    "Konum (yaklaşık)":"android.permission.ACCESS_COARSE_LOCATION",
    "Konum (hassas)":"android.permission.ACCESS_FINE_LOCATION",
    "Bildirim":"android.permission.POST_NOTIFICATIONS",
    "Titreşim":"android.permission.VIBRATE",
    "Ağ durumu":"android.permission.ACCESS_NETWORK_STATE",
}

def safe_extract(src:Path,dst:Path):
    dst=dst.resolve()
    with zipfile.ZipFile(src) as z:
        for m in z.infolist():
            target=(dst/m.filename).resolve()
            if os.path.commonpath([str(dst),str(target)])!=str(dst):
                raise RuntimeError("Güvenli olmayan ZIP yolu bulundu.")
        z.extractall(dst)

def run_capture(cmd,cwd=None,env=None):
    try:
        p=subprocess.run(cmd,cwd=str(cwd) if cwd else None,env=env,capture_output=True,text=True,encoding="utf-8",errors="replace",timeout=30)
        return p.returncode,(p.stdout or "")+(p.stderr or "")
    except Exception as e:
        return 1,str(e)

def detect_java():
    c=[]
    if os.getenv("JAVA_HOME"): c.append(Path(os.environ["JAVA_HOME"]))
    pf=Path(os.getenv("ProgramFiles",r"C:\Program Files"))
    c += [pf/"Android"/"Android Studio"/"jbr"]
    microsoft=pf/"Microsoft"
    if microsoft.exists():
        c += sorted([p for p in microsoft.glob("jdk-17*") if p.is_dir()], reverse=True)
    for x in c:
        if (x/"bin"/"java.exe").exists(): return x
    j=shutil.which("java")
    return Path(j).resolve().parent.parent if j else None

def detect_sdk():
    for k in ("ANDROID_HOME","ANDROID_SDK_ROOT"):
        v=os.getenv(k)
        if v and Path(v).exists(): return Path(v)
    p=Path(os.getenv("LOCALAPPDATA",""))/"Android"/"Sdk"
    return p if p.exists() else None

def sdk_tool(name):
    sdk=detect_sdk()
    if not sdk: return None
    candidates=[
        sdk/"platform-tools"/f"{name}.exe",
        sdk/"build-tools"/BUILD_TOOLS/f"{name}.exe",
        sdk/"cmdline-tools"/"latest"/"bin"/f"{name}.bat",
    ]
    for c in candidates:
        if c.exists(): return c
    return Path(shutil.which(name)) if shutil.which(name) else None

def find_root(p:Path):
    if (p/"settings.gradle").exists() or (p/"settings.gradle.kts").exists(): return p
    for f in p.rglob("settings.gradle*"):
        if len(f.relative_to(p).parts)<=5: return f.parent
    return None

def ensure_gradle(log):
    home=CACHE/f"gradle-{GRADLE}"
    exe=home/"bin"/"gradle.bat"
    if exe.exists(): return exe
    sysg=shutil.which("gradle")
    if sysg: return Path(sysg)
    zp=CACHE/f"gradle-{GRADLE}-bin.zip"
    log(f"Gradle {GRADLE} indiriliyor...")
    urllib.request.urlretrieve(f"https://services.gradle.org/distributions/gradle-{GRADLE}-bin.zip",zp)
    with zipfile.ZipFile(zp) as z: z.extractall(CACHE)
    if not exe.exists(): raise RuntimeError("Gradle kurulamadı.")
    return exe

def normalize_pkg(pkg):
    pkg=re.sub(r"[^a-z0-9_.]","",pkg.lower()).strip(".")
    if "." not in pkg: pkg="com.apkkurucu."+pkg
    return pkg or "com.apkkurucu.uygulamam"

def xml_escape(s):
    return s.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;").replace('"',"&quot;")

def html_project(src,project,name,pkg,http,permissions,url=None,version_name="1.0",version_code=1,orientation="unspecified"):
    app=project/"app"
    assets=app/"src"/"main"/"assets"/"www"
    values=app/"src"/"main"/"res"/"values"
    java=app/"src"/"main"/"java"/Path(*pkg.split("."))
    assets.mkdir(parents=True); values.mkdir(parents=True); java.mkdir(parents=True)

    if url:
        html='<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"><meta charset="utf-8"><title>'+xml_escape(name)+'</title></head><body style="font-family:sans-serif;text-align:center;padding:30px"><p>Web uygulaması yükleniyor...</p></body></html>'
        (assets/"index.html").write_text(html,encoding="utf-8")
    elif src and src.is_file() and src.suffix.lower() in (".html",".htm"):
        shutil.copy2(src,assets/"index.html")
        for x in src.parent.iterdir():
            if x!=src and x.is_file() and x.suffix.lower() in {".css",".js",".png",".jpg",".jpeg",".svg",".webp",".json",".mp3",".mp4",".woff",".woff2",".ttf",".ico"}:
                shutil.copy2(x,assets/x.name)
    elif src:
        temp=project/"websrc"; temp.mkdir()
        if src.is_file(): safe_extract(src,temp)
        else: shutil.copytree(src,temp,dirs_exist_ok=True)
        indexes=list(temp.rglob("index.html"))
        if not indexes: raise RuntimeError("HTML paketi içinde index.html bulunamadı.")
        shutil.copytree(indexes[0].parent,assets,dirs_exist_ok=True)
        shutil.rmtree(temp,ignore_errors=True)

    (project/"settings.gradle").write_text(
        "pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\n"
        "dependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\n"
        "rootProject.name='APKApp'\ninclude ':app'\n",encoding="utf-8")
    (project/"build.gradle").write_text(f"plugins {{ id 'com.android.application' version '{AGP}' apply false }}\n",encoding="utf-8")
    (project/"gradle.properties").write_text("org.gradle.jvmargs=-Xmx3072m -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\n",encoding="utf-8")
    (app/"build.gradle").write_text(
        f"plugins {{ id 'com.android.application' }}\nandroid {{ namespace '{pkg}'; compileSdk {SDK_API}; "
        f"defaultConfig {{ applicationId '{pkg}'; minSdk 23; targetSdk {SDK_API}; versionCode {int(version_code)}; versionName '{version_name}' }} }}\n",encoding="utf-8")

    selected=set(permissions)
    selected.add("android.permission.INTERNET")
    uses="".join(f'<uses-permission android:name="{p}"/>' for p in sorted(selected))
    clear="true" if http or (url and url.lower().startswith("http://")) else "false"
    ori="" if orientation=="unspecified" else f' android:screenOrientation="{orientation}"'
    manifest=f'<manifest xmlns:android="http://schemas.android.com/apk/res/android">{uses}<application android:theme="@style/AppTheme" android:label="@string/app_name" android:usesCleartextTraffic="{clear}"><activity android:name=".MainActivity" android:exported="true"{ori}><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>'
    (app/"src"/"main"/"AndroidManifest.xml").write_text(manifest,encoding="utf-8")
    (values/"strings.xml").write_text(f'<resources><string name="app_name">{xml_escape(name)}</string></resources>',encoding="utf-8")
    (values/"styles.xml").write_text('<resources><style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar"/></resources>',encoding="utf-8")
    start=url or "file:///android_asset/www/index.html"
    activity=f'''package {pkg};
import android.app.*;
import android.os.*;
import android.webkit.*;
public class MainActivity extends Activity {{
  private WebView w;
  public void onCreate(Bundle b){{
    super.onCreate(b);
    w=new WebView(this); setContentView(w);
    WebSettings s=w.getSettings();
    s.setJavaScriptEnabled(true); s.setDomStorageEnabled(true); s.setDatabaseEnabled(true);
    s.setAllowFileAccess(true); s.setAllowContentAccess(true); s.setMediaPlaybackRequiresUserGesture(false);
    w.setWebChromeClient(new WebChromeClient());
    w.setWebViewClient(new WebViewClient());
    w.loadUrl("{start}");
  }}
  @Override public void onBackPressed(){{ if(w.canGoBack()) w.goBack(); else super.onBackPressed(); }}
}}'''
    (java/"MainActivity.java").write_text(activity,encoding="utf-8")

def run_build(cmd,cwd,env,log):
    p=subprocess.Popen(cmd,cwd=str(cwd),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
        text=True,encoding="utf-8",errors="replace",
        creationflags=subprocess.CREATE_NO_WINDOW if os.name=="nt" else 0)
    for line in p.stdout: log(line.rstrip())
    return p.wait()

def analyze_source(src_text):
    report=[]
    if re.match(r"^https?://",src_text.strip(),re.I):
        return ["Tür: Web adresi / PWA","Dönüşüm: WebView tabanlı Android uygulaması"]
    p=Path(src_text)
    if not p.exists(): return ["Kaynak bulunamadı."]
    if p.is_dir():
        report.append("Tür: Android/Gradle proje klasörü" if find_root(p) else "Tür: Web proje klasörü")
    elif p.suffix.lower() in (".html",".htm"): report.append("Tür: HTML dosyası")
    elif p.suffix.lower()==".zip":
        report.append("Tür: ZIP paketi")
        try:
            with zipfile.ZipFile(p) as z: names=z.namelist()
            report.append("Android Gradle yapısı bulundu." if any(n.endswith(("settings.gradle","settings.gradle.kts")) for n in names) else "Web/HTML ZIP olarak değerlendirilecek.")
        except: report.append("ZIP okunamadı.")
    elif p.suffix.lower()==".apk": report.append("Tür: APK")
    else: report.append(f"Tür: {p.suffix or 'bilinmiyor'}")
    return report

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(f"{APP} {VERSION}")
        self.geometry("1100x760"); self.minsize(980,680)
        self.src=tk.StringVar(); self.name=tk.StringVar(value="Uygulamam"); self.pkg=tk.StringVar(value="com.apkkurucu.uygulamam")
        self.http=tk.BooleanVar(); self.release=tk.BooleanVar(); self.aab=tk.BooleanVar()
        self.version_name=tk.StringVar(value="1.0"); self.version_code=tk.IntVar(value=1)
        self.orientation=tk.StringVar(value="unspecified")
        self.perm_vars={k:tk.BooleanVar(value=(k=="İnternet")) for k in PERMISSIONS}
        self.make()

    def make(self):
        root=ttk.Frame(self,padding=12); root.pack(fill="both",expand=True)
        ttk.Label(root,text="APK Dönüştürücü Pro",font=("Segoe UI",22,"bold")).pack(anchor="w")
        ttk.Label(root,text="Analiz Et → Düzelt → Derle → İmzala → Test Et").pack(anchor="w",pady=(0,8))
        self.tabs=ttk.Notebook(root); self.tabs.pack(fill="both",expand=True)
        self.build_tab=ttk.Frame(self.tabs,padding=12); self.tools_tab=ttk.Frame(self.tabs,padding=12); self.sign_tab=ttk.Frame(self.tabs,padding=12); self.analyze_tab=ttk.Frame(self.tabs,padding=12)
        self.tabs.add(self.build_tab,text="Dönüştür"); self.tabs.add(self.tools_tab,text="Cihaz / Doctor"); self.tabs.add(self.sign_tab,text="İmzalama"); self.tabs.add(self.analyze_tab,text="APK Analizi")
        self.make_build(); self.make_tools(); self.make_sign(); self.make_analyze()

    def make_build(self):
        f=self.build_tab
        srcf=ttk.LabelFrame(f,text="Kaynak",padding=8); srcf.pack(fill="x")
        ttk.Entry(srcf,textvariable=self.src).pack(side="left",fill="x",expand=True)
        ttk.Button(srcf,text="Dosya",command=self.file).pack(side="left",padx=4)
        ttk.Button(srcf,text="Klasör",command=self.folder).pack(side="left")
        ttk.Button(srcf,text="URL",command=self.url).pack(side="left",padx=(4,0))
        ttk.Button(srcf,text="Analiz Et",command=self.analyze_current).pack(side="left",padx=(4,0))

        cfg=ttk.LabelFrame(f,text="Uygulama Ayarları",padding=8); cfg.pack(fill="x",pady=8)
        labels=[("Uygulama adı",self.name),("Paket adı",self.pkg),("Sürüm adı",self.version_name)]
        for i,(lab,var) in enumerate(labels):
            ttk.Label(cfg,text=lab).grid(row=i,column=0,sticky="w")
            ttk.Entry(cfg,textvariable=var).grid(row=i,column=1,sticky="ew",padx=6,pady=2)
        ttk.Label(cfg,text="Sürüm kodu").grid(row=0,column=2,sticky="w")
        ttk.Spinbox(cfg,from_=1,to=999999,textvariable=self.version_code,width=10).grid(row=0,column=3,sticky="w",padx=6)
        ttk.Label(cfg,text="Ekran yönü").grid(row=1,column=2,sticky="w")
        ttk.Combobox(cfg,textvariable=self.orientation,values=["unspecified","portrait","landscape"],state="readonly",width=14).grid(row=1,column=3,sticky="w",padx=6)
        ttk.Checkbutton(cfg,text="HTTP bağlantılarına izin ver",variable=self.http).grid(row=2,column=2,columnspan=2,sticky="w")
        ttk.Checkbutton(cfg,text="Release",variable=self.release).grid(row=3,column=0,sticky="w")
        ttk.Checkbutton(cfg,text="AAB de oluştur",variable=self.aab).grid(row=3,column=1,sticky="w")
        cfg.columnconfigure(1,weight=1)

        pf=ttk.LabelFrame(f,text="İzinler",padding=8); pf.pack(fill="x",pady=(0,8))
        for i,(name,var) in enumerate(self.perm_vars.items()):
            ttk.Checkbutton(pf,text=name,variable=var).grid(row=i//4,column=i%4,sticky="w",padx=6,pady=2)

        bar=ttk.Frame(f); bar.pack(fill="x")
        ttk.Button(bar,text="APK / AAB OLUŞTUR",command=self.start).pack(side="left")
        ttk.Button(bar,text="Çıktıları Aç",command=lambda:os.startfile(OUTPUTS)).pack(side="left",padx=6)
        ttk.Button(bar,text="Profil Kaydet",command=self.save_profile).pack(side="left")
        ttk.Button(bar,text="Profil Yükle",command=self.load_profile).pack(side="left",padx=6)
        self.status=ttk.Label(f,text="Hazır"); self.status.pack(anchor="w",pady=6)
        self.logbox=tk.Text(f,font=("Consolas",9),height=16); self.logbox.pack(fill="both",expand=True)

    def make_tools(self):
        f=self.tools_tab
        ttk.Button(f,text="Sistem / Build Doctor",command=self.doctor).pack(anchor="w")
        ttk.Button(f,text="ADB Cihazları",command=self.devices).pack(anchor="w",pady=5)
        ttk.Button(f,text="APK Telefona Kur",command=self.install_apk).pack(anchor="w")
        ttk.Button(f,text="ADB Logcat Başlat",command=self.logcat).pack(anchor="w",pady=5)
        self.tooltext=tk.Text(f,font=("Consolas",10)); self.tooltext.pack(fill="both",expand=True,pady=8)

    def make_sign(self):
        f=self.sign_tab
        ttk.Label(f,text="Keystore ve imza araçları",font=("Segoe UI",14,"bold")).pack(anchor="w")
        ttk.Button(f,text="Yeni Keystore Oluştur",command=self.make_keystore).pack(anchor="w",pady=8)
        ttk.Button(f,text="APK İmzasını Doğrula",command=self.verify_apk).pack(anchor="w")
        ttk.Label(f,text="Release AAB/APK için Gradle signingConfig kullanabilirsiniz. Bu merkez keystore üretimi ve APK imza doğrulaması sağlar.",wraplength=760).pack(anchor="w",pady=10)

    def make_analyze(self):
        f=self.analyze_tab
        ttk.Button(f,text="APK Seç ve Analiz Et",command=self.apk_analyze).pack(anchor="w")
        self.apktext=tk.Text(f,font=("Consolas",10)); self.apktext.pack(fill="both",expand=True,pady=8)

    def file(self):
        p=filedialog.askopenfilename(filetypes=[("Desteklenen","*.html *.htm *.zip *.apk"),("Tümü","*.*")])
        if p: self.src.set(p); self.name.set(Path(p).stem)

    def folder(self):
        p=filedialog.askdirectory()
        if p: self.src.set(p); self.name.set(Path(p).name)

    def url(self):
        u=simpledialog.askstring("Web adresi","https:// ile başlayan adresi girin:")
        if u:
            self.src.set(u)
            self.name.set(re.sub(r"^www\.","",re.sub(r"^https?://","",u)).split("/")[0] or "WebUygulama")

    def log(self,s):
        self.after(0,lambda:(self.logbox.insert("end",s+"\n"),self.logbox.see("end")))

    def analyze_current(self):
        self.logbox.delete("1.0","end")
        for x in analyze_source(self.src.get()): self.log(x)

    def doctor(self):
        java=detect_java(); sdk=detect_sdk(); adb=sdk_tool("adb"); signer=sdk_tool("apksigner")
        lines=[f"JDK: {java or 'YOK'}",f"Android SDK: {sdk or 'YOK'}",f"ADB: {adb or 'YOK'}",f"apksigner: {signer or 'YOK'}"]
        if java:
            _,o=run_capture([str(java/"bin"/"java.exe"),"-version"]); lines.append(o.strip())
        if sdk:
            lines.append(f"API {SDK_API}: {'OK' if (sdk/'platforms'/f'android-{SDK_API}').exists() else 'EKSİK'}")
            lines.append(f"Build Tools {BUILD_TOOLS}: {'OK' if (sdk/'build-tools'/BUILD_TOOLS).exists() else 'EKSİK'}")
        self.tooltext.delete("1.0","end"); self.tooltext.insert("end","\n".join(lines))

    def devices(self):
        adb=sdk_tool("adb")
        if not adb: return messagebox.showerror("ADB","ADB bulunamadı.")
        _,o=run_capture([str(adb),"devices","-l"]); self.tooltext.delete("1.0","end"); self.tooltext.insert("end",o)

    def install_apk(self):
        adb=sdk_tool("adb")
        if not adb: return messagebox.showerror("ADB","ADB bulunamadı.")
        apk=filedialog.askopenfilename(filetypes=[("APK","*.apk")])
        if not apk:return
        code,o=run_capture([str(adb),"install","-r",apk]); self.tooltext.delete("1.0","end"); self.tooltext.insert("end",o)
        messagebox.showinfo("ADB","Kurulum başarılı." if code==0 else "Kurulum başarısız; ayrıntıya bakın.")

    def logcat(self):
        adb=sdk_tool("adb")
        if not adb:return messagebox.showerror("ADB","ADB bulunamadı.")
        subprocess.Popen(["cmd","/c","start","cmd","/k",str(adb),"logcat"])

    def make_keystore(self):
        java=detect_java()
        if not java:return messagebox.showerror("Keystore","JDK bulunamadı.")
        out=filedialog.asksaveasfilename(defaultextension=".jks",filetypes=[("Java Keystore","*.jks")])
        if not out:return
        alias=simpledialog.askstring("Alias","Anahtar alias adı:",initialvalue="upload") or "upload"
        pwd=simpledialog.askstring("Parola","Keystore parolası:",show="*")
        if not pwd:return
        cmd=[str(java/"bin"/"keytool.exe"),"-genkeypair","-v","-keystore",out,"-alias",alias,"-keyalg","RSA","-keysize","4096","-validity","10000","-storepass",pwd,"-keypass",pwd,"-dname","CN=Android Developer, OU=Mobile, O=App, L=Istanbul, S=Istanbul, C=TR"]
        code,o=run_capture(cmd); messagebox.showinfo("Keystore",o[-2000:] if code else f"Oluşturuldu:\n{out}")

    def verify_apk(self):
        signer=sdk_tool("apksigner")
        if not signer:return messagebox.showerror("İmza","apksigner bulunamadı.")
        apk=filedialog.askopenfilename(filetypes=[("APK","*.apk")])
        if not apk:return
        code,o=run_capture([str(signer),"verify","--verbose","--print-certs",apk])
        messagebox.showinfo("İmza sonucu",o[-5000:] if o else ("Geçerli" if code==0 else "Geçersiz"))

    def apk_analyze(self):
        apk=filedialog.askopenfilename(filetypes=[("APK","*.apk")])
        if not apk:return
        p=Path(apk)
        h=hashlib.sha256()
        with p.open("rb") as f:
            for chunk in iter(lambda:f.read(1024*1024),b""): h.update(chunk)
        lines=[f"Dosya: {p.name}",f"Boyut: {p.stat().st_size/1024/1024:.2f} MB",f"SHA256: {h.hexdigest()}"]
        aapt=sdk_tool("aapt")
        if aapt:
            _,o=run_capture([str(aapt),"dump","badging",apk]); lines.append(o[:8000])
        signer=sdk_tool("apksigner")
        if signer:
            _,o=run_capture([str(signer),"verify","--print-certs",apk]); lines.append("\nİMZA:\n"+o[:5000])
        self.apktext.delete("1.0","end"); self.apktext.insert("end","\n".join(lines))

    def save_profile(self):
        fn=filedialog.asksaveasfilename(initialdir=PROFILES,defaultextension=".json",filetypes=[("Profil","*.json")])
        if not fn:return
        data={"name":self.name.get(),"pkg":self.pkg.get(),"version_name":self.version_name.get(),"version_code":self.version_code.get(),"orientation":self.orientation.get(),"http":self.http.get(),"release":self.release.get(),"aab":self.aab.get(),"permissions":[k for k,v in self.perm_vars.items() if v.get()]}
        Path(fn).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding="utf-8")

    def load_profile(self):
        fn=filedialog.askopenfilename(initialdir=PROFILES,filetypes=[("Profil","*.json")])
        if not fn:return
        d=json.loads(Path(fn).read_text(encoding="utf-8"))
        self.name.set(d.get("name","Uygulamam")); self.pkg.set(d.get("pkg","com.apkkurucu.uygulamam")); self.version_name.set(d.get("version_name","1.0")); self.version_code.set(d.get("version_code",1)); self.orientation.set(d.get("orientation","unspecified")); self.http.set(d.get("http",False)); self.release.set(d.get("release",False)); self.aab.set(d.get("aab",False))
        for k,v in self.perm_vars.items(): v.set(k in d.get("permissions",[]))

    def start(self):
        threading.Thread(target=self.worker,daemon=True).start()

    def worker(self):
        try:
            src_text=self.src.get().strip()
            if not src_text: raise RuntimeError("Kaynak seçilmedi.")
            java=detect_java(); sdk=detect_sdk()
            if not java: raise RuntimeError("JDK bulunamadı. Android Studio veya JDK 17 kurun.")
            if not sdk: raise RuntimeError("Android SDK bulunamadı. Android Studio SDK Manager ile kurun.")
            gradle=ensure_gradle(self.log)
            stamp=time.strftime("%Y%m%d_%H%M%S"); project=BUILDS/f"build_{stamp}"; project.mkdir()
            pkg=normalize_pkg(self.pkg.get())
            perms=[PERMISSIONS[k] for k,v in self.perm_vars.items() if v.get()]
            is_url=bool(re.match(r"^https?://",src_text,re.I))
            root=None
            if is_url:
                html_project(None,project,self.name.get(),pkg,self.http.get(),perms,url=src_text,version_name=self.version_name.get(),version_code=self.version_code.get(),orientation=self.orientation.get()); root=project
            else:
                src=Path(src_text)
                if not src.exists(): raise RuntimeError("Kaynak bulunamadı.")
                if src.suffix.lower()==".apk": raise RuntimeError("APK dosyası kaynak olarak derlenmez; APK Analizi sekmesini kullanın.")
                if src.is_dir() and find_root(src):
                    shutil.copytree(src,project,dirs_exist_ok=True); root=find_root(project)
                elif src.suffix.lower()==".zip":
                    probe=project/"probe"; probe.mkdir(); safe_extract(src,probe); ar=find_root(probe)
                    if ar: root=ar
                    else:
                        shutil.rmtree(probe); html_project(src,project,self.name.get(),pkg,self.http.get(),perms,version_name=self.version_name.get(),version_code=self.version_code.get(),orientation=self.orientation.get()); root=project
                else:
                    html_project(src,project,self.name.get(),pkg,self.http.get(),perms,version_name=self.version_name.get(),version_code=self.version_code.get(),orientation=self.orientation.get()); root=project
            env=os.environ.copy(); env["JAVA_HOME"]=str(java); env["ANDROID_HOME"]=str(sdk); env["ANDROID_SDK_ROOT"]=str(sdk)
            wrapper=root/"gradlew.bat"; exe=wrapper if wrapper.exists() else gradle
            tasks=["assembleRelease" if self.release.get() else "assembleDebug"]
            if self.aab.get(): tasks.append("bundleRelease" if self.release.get() else "bundleDebug")
            for task in tasks:
                self.log(f"Derleniyor: {task}")
                code=run_build([str(exe),task,"--stacktrace"],root,env,self.log)
                if code: raise RuntimeError(f"Gradle görevi başarısız: {task}")
            artifacts=[x for x in root.rglob("*") if x.suffix.lower() in (".apk",".aab") and "outputs" in x.parts]
            if not artifacts: raise RuntimeError("APK/AAB bulunamadı.")
            out=OUTPUTS/f"{re.sub(r'[^A-Za-z0-9_-]','_',self.name.get())}_{stamp}"; out.mkdir()
            copied=[]
            for x in artifacts:
                d=out/x.name; shutil.copy2(x,d); copied.append(d)
            self.log("TAMAMLANDI")
            messagebox.showinfo("Tamamlandı","Hazır:\n"+"\n".join(map(str,copied)))
        except Exception as e:
            self.log("HATA: "+str(e)); messagebox.showerror("Hata",str(e))

if __name__=="__main__":
    App().mainloop()
