from __future__ import annotations
import os,re,shutil,subprocess,threading,time,zipfile,urllib.request,json,hashlib
from pathlib import Path
import tkinter as tk
from tkinter import ttk,filedialog,messagebox,simpledialog

APP='APK Dönüştürücü Pro'; VERSION='6.1'; GRADLE='9.6.0'; AGP='9.4.0'; SDK_API=37; BUILD_TOOLS='36.0.0'
ROOT=Path.home()/'APKDonusturucuPro'; CACHE=ROOT/'cache'; BUILDS=ROOT/'builds'; OUTPUTS=ROOT/'outputs'; PROFILES=ROOT/'profiles'
for p in (CACHE,BUILDS,OUTPUTS,PROFILES): p.mkdir(parents=True,exist_ok=True)
PERMISSIONS={'İnternet':'android.permission.INTERNET','Kamera':'android.permission.CAMERA','Mikrofon':'android.permission.RECORD_AUDIO','Konum (yaklaşık)':'android.permission.ACCESS_COARSE_LOCATION','Konum (hassas)':'android.permission.ACCESS_FINE_LOCATION','Bildirim':'android.permission.POST_NOTIFICATIONS','Titreşim':'android.permission.VIBRATE','Ağ durumu':'android.permission.ACCESS_NETWORK_STATE'}
DANGEROUS={'android.permission.CAMERA','android.permission.RECORD_AUDIO','android.permission.ACCESS_COARSE_LOCATION','android.permission.ACCESS_FINE_LOCATION','android.permission.POST_NOTIFICATIONS'}

def run_capture(cmd,cwd=None,env=None,timeout=60):
    try:
        p=subprocess.run(cmd,cwd=str(cwd) if cwd else None,env=env,capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=timeout,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
        return p.returncode,(p.stdout or '')+(p.stderr or '')
    except Exception as e:return 1,str(e)

def safe_extract(src,dst):
    dst=Path(dst).resolve()
    with zipfile.ZipFile(src) as z:
        for m in z.infolist():
            t=(dst/m.filename).resolve()
            if os.path.commonpath([str(dst),str(t)])!=str(dst): raise RuntimeError('Güvenli olmayan ZIP yolu bulundu.')
        z.extractall(dst)

def detect_java():
    c=[]; pf=Path(os.getenv('ProgramFiles',r'C:\Program Files'))
    if os.getenv('JAVA_HOME'): c.append(Path(os.environ['JAVA_HOME']))
    c.append(pf/'Android'/'Android Studio'/'jbr')
    for base in (pf/'Microsoft',pf/'Java',pf/'Eclipse Adoptium'):
        if base.exists(): c += [p for p in base.iterdir() if p.is_dir() and ('17' in p.name or 'jdk' in p.name.lower())]
    j=shutil.which('java')
    if j:c.append(Path(j).resolve().parent.parent)
    for x in c:
        exe=x/'bin'/('java.exe' if os.name=='nt' else 'java')
        if exe.exists(): return x
    return None

def java_major(java):
    exe=java/'bin'/('java.exe' if os.name=='nt' else 'java'); _,o=run_capture([str(exe),'-version'])
    m=re.search(r'version\s+"(\d+)',o); return int(m.group(1)) if m else None

def detect_sdk():
    for k in ('ANDROID_HOME','ANDROID_SDK_ROOT'):
        v=os.getenv(k)
        if v and Path(v).exists(): return Path(v)
    p=Path(os.getenv('LOCALAPPDATA',''))/'Android'/'Sdk'; return p if p.exists() else None

def sdk_tool(name):
    sdk=detect_sdk(); ext='.exe' if os.name=='nt' else ''; bat='.bat' if os.name=='nt' else ''; c=[]
    if sdk:
        c += [sdk/'platform-tools'/f'{name}{ext}',sdk/'build-tools'/BUILD_TOOLS/f'{name}{ext}',sdk/'cmdline-tools'/'latest'/'bin'/f'{name}{bat}']
        bt=sdk/'build-tools'
        if bt.exists():
            for d in sorted([x for x in bt.iterdir() if x.is_dir()],reverse=True): c.append(d/f'{name}{ext}')
    for x in c:
        if x.exists(): return x
    f=shutil.which(name); return Path(f) if f else None

def sdkmanager_path(sdk):
    suf='.bat' if os.name=='nt' else ''; c=[sdk/'cmdline-tools'/'latest'/'bin'/f'sdkmanager{suf}']; cr=sdk/'cmdline-tools'
    if cr.exists(): c += [d/'bin'/f'sdkmanager{suf}' for d in cr.iterdir() if d.is_dir()]
    return next((x for x in c if x.exists()),None)

def ensure_sdk(sdk,java,log):
    miss=[]
    if not (sdk/'platforms'/f'android-{SDK_API}').exists(): miss.append(f'platforms;android-{SDK_API}')
    if not (sdk/'build-tools'/BUILD_TOOLS).exists(): miss.append(f'build-tools;{BUILD_TOOLS}')
    if not (sdk/'platform-tools').exists(): miss.append('platform-tools')
    if not miss:return
    sm=sdkmanager_path(sdk)
    if not sm: raise RuntimeError('Eksik SDK bileşenleri var ve sdkmanager bulunamadı. Android SDK Command-line Tools yükleyin.')
    env=os.environ.copy(); env.update(JAVA_HOME=str(java),ANDROID_HOME=str(sdk),ANDROID_SDK_ROOT=str(sdk)); log('SDK bileşenleri kuruluyor: '+', '.join(miss))
    code,o=run_capture([str(sm),*miss],env=env,timeout=600)
    for line in o.splitlines()[-40:]:log(line)
    if code: raise RuntimeError('Android SDK bileşenleri kurulamadı.')

def find_root(p):
    p=Path(p)
    if (p/'settings.gradle').exists() or (p/'settings.gradle.kts').exists(): return p
    for f in p.rglob('settings.gradle*'):
        if len(f.relative_to(p).parts)<=5:return f.parent
    return None

def ensure_gradle(log):
    exe=CACHE/f'gradle-{GRADLE}'/'bin'/('gradle.bat' if os.name=='nt' else 'gradle')
    if exe.exists():return exe
    g=shutil.which('gradle')
    if g:return Path(g)
    z=CACHE/f'gradle-{GRADLE}-bin.zip'
    if not z.exists():log(f'Gradle {GRADLE} indiriliyor...');urllib.request.urlretrieve(f'https://services.gradle.org/distributions/gradle-{GRADLE}-bin.zip',z)
    with zipfile.ZipFile(z) as q:q.extractall(CACHE)
    if not exe.exists():raise RuntimeError('Gradle kurulamadı.')
    return exe

def normalize_pkg(v):
    parts=[re.sub(r'[^a-z0-9_]','',x) for x in v.lower().strip().split('.')];parts=[x for x in parts if x]
    if len(parts)<2:parts=['com','apkkurucu']+(parts or ['uygulamam'])
    return '.'.join(('p'+x if x[0].isdigit() else x) for x in parts)

def esc_xml(s):return str(s).replace('&','&amp;').replace('<','&lt;').replace('>','&gt;').replace('"','&quot;').replace("'",'&apos;')
def esc_g(s):return str(s).replace('\\','\\\\').replace("'","\\'").replace('\n',' ')
def esc_j(s):return str(s).replace('\\','\\\\').replace('"','\\"').replace('\n','\\n').replace('\r','')

def copy_web(src,dst,limit=300*1024*1024):
    total=0;skip={'.git','node_modules','build','dist','__pycache__','.idea','.gradle'}
    for root,dirs,files in os.walk(src):
        dirs[:]=[d for d in dirs if d not in skip and not (Path(root)/d).is_symlink()];out=Path(dst)/Path(root).relative_to(src);out.mkdir(parents=True,exist_ok=True)
        for fn in files:
            s=Path(root)/fn
            if s.is_symlink():continue
            total+=s.stat().st_size
            if total>limit:raise RuntimeError('Web proje boyutu 300 MB sınırını aşıyor.')
            shutil.copy2(s,out/fn)

def signing_block(cfg):
    if not cfg:return ''
    ks,alias,sp,kp=cfg;path=esc_g(str(Path(ks).resolve()).replace('\\','/'))
    return f"signingConfigs {{ release {{ storeFile file('{path}'); storePassword '{esc_g(sp)}'; keyAlias '{esc_g(alias)}'; keyPassword '{esc_g(kp)}' }} }} buildTypes {{ release {{ signingConfig signingConfigs.release; minifyEnabled false }} }}"

def html_project(src,project,name,pkg,http,permissions,url=None,version_name='1.0',version_code=1,orientation='unspecified',signing=None):
    app=project/'app';assets=app/'src'/'main'/'assets'/'www';values=app/'src'/'main'/'res'/'values';java=app/'src'/'main'/'java'/Path(*pkg.split('.'))
    assets.mkdir(parents=True);values.mkdir(parents=True);java.mkdir(parents=True)
    if url:(assets/'index.html').write_text('<!doctype html><html><body>Web uygulaması yükleniyor...</body></html>',encoding='utf-8')
    elif src and src.is_file() and src.suffix.lower() in ('.html','.htm'):
        copy_web(src.parent,assets)
        if src.name.lower()!='index.html':shutil.copy2(src,assets/'index.html')
    elif src:
        tmp=project/'websrc';tmp.mkdir();safe_extract(src,tmp) if src.is_file() else copy_web(src,tmp);idx=list(tmp.rglob('index.html'))
        if not idx:raise RuntimeError('HTML paketi içinde index.html bulunamadı.')
        copy_web(idx[0].parent,assets);shutil.rmtree(tmp,ignore_errors=True)
    (project/'settings.gradle').write_text("pluginManagement { repositories { google(); mavenCentral(); gradlePluginPortal() } }\ndependencyResolutionManagement { repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS); repositories { google(); mavenCentral() } }\nrootProject.name='APKApp'\ninclude ':app'\n",encoding='utf-8')
    (project/'build.gradle').write_text(f"plugins {{ id 'com.android.application' version '{AGP}' apply false }}\n",encoding='utf-8')
    (project/'gradle.properties').write_text('org.gradle.jvmargs=-Xmx3072m -Dfile.encoding=UTF-8\nandroid.useAndroidX=true\n',encoding='utf-8')
    sign=signing_block(signing);(app/'build.gradle').write_text(f"plugins {{ id 'com.android.application' }}\nandroid {{ namespace '{pkg}'; compileSdk {SDK_API}; defaultConfig {{ applicationId '{pkg}'; minSdk 23; targetSdk {SDK_API}; versionCode {int(version_code)}; versionName '{esc_g(version_name)}' }} {sign} }}\n",encoding='utf-8')
    selected=set(permissions)|{'android.permission.INTERNET'};uses=''.join(f'<uses-permission android:name="{p}"/>' for p in sorted(selected));clear='true' if http or (url and url.lower().startswith('http://')) else 'false';ori='' if orientation=='unspecified' else f' android:screenOrientation="{orientation}"'
    (app/'src'/'main'/'AndroidManifest.xml').write_text(f'<manifest xmlns:android="http://schemas.android.com/apk/res/android">{uses}<application android:theme="@style/AppTheme" android:label="@string/app_name" android:usesCleartextTraffic="{clear}"><activity android:name=".MainActivity" android:exported="true"{ori}><intent-filter><action android:name="android.intent.action.MAIN"/><category android:name="android.intent.category.LAUNCHER"/></intent-filter></activity></application></manifest>',encoding='utf-8')
    (values/'strings.xml').write_text(f'<resources><string name="app_name">{esc_xml(name)}</string></resources>',encoding='utf-8');(values/'styles.xml').write_text('<resources><style name="AppTheme" parent="android:style/Theme.Material.Light.NoActionBar"/></resources>',encoding='utf-8')
    perms=','.join('"'+esc_j(p)+'"' for p in selected if p in DANGEROUS);start=esc_j(url or 'file:///android_asset/www/index.html')
    activity=f'''package {pkg};\nimport android.app.*; import android.os.*; import android.content.*; import android.net.Uri; import android.webkit.*;\npublic class MainActivity extends Activity {{ private WebView w; private ValueCallback<Uri[]> cb; private static final int FILE=5001,PERM=5002; private final String[] rp=new String[]{{{perms}}}; public void onCreate(Bundle b){{super.onCreate(b);w=new WebView(this);setContentView(w);WebSettings s=w.getSettings();s.setJavaScriptEnabled(true);s.setDomStorageEnabled(true);s.setDatabaseEnabled(true);s.setAllowFileAccess(true);s.setAllowContentAccess(true);s.setMediaPlaybackRequiresUserGesture(false);w.setWebViewClient(new WebViewClient());w.setWebChromeClient(new WebChromeClient(){{public boolean onShowFileChooser(WebView v,ValueCallback<Uri[]> c,FileChooserParams p){{if(cb!=null)cb.onReceiveValue(null);cb=c;try{{startActivityForResult(p.createIntent(),FILE);return true;}}catch(Exception e){{cb=null;return false;}}}} public void onGeolocationPermissionsShowPrompt(String o,GeolocationPermissions.Callback c){{c.invoke(o,true,false);}}}});if(Build.VERSION.SDK_INT>=23&&rp.length>0)requestPermissions(rp,PERM);w.loadUrl("{start}");}} protected void onActivityResult(int r,int c,Intent d){{super.onActivityResult(r,c,d);if(r==FILE&&cb!=null){{cb.onReceiveValue(WebChromeClient.FileChooserParams.parseResult(c,d));cb=null;}}}} public void onBackPressed(){{if(w.canGoBack())w.goBack();else super.onBackPressed();}} }}'''
    (java/'MainActivity.java').write_text(activity,encoding='utf-8')

def run_build(cmd,cwd,env,log):
    p=subprocess.Popen(cmd,cwd=str(cwd),env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf-8',errors='replace',creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
    for line in p.stdout:log(line.rstrip())
    return p.wait()

class App(tk.Tk):
    def __init__(self):
        super().__init__();self.title(f'{APP} {VERSION}');self.geometry('1160x800');self.minsize(1000,700);self.building=False
        self.src=tk.StringVar();self.name=tk.StringVar(value='Uygulamam');self.pkg=tk.StringVar(value='com.apkkurucu.uygulamam');self.http=tk.BooleanVar();self.release=tk.BooleanVar();self.aab=tk.BooleanVar();self.version_name=tk.StringVar(value='1.0');self.version_code=tk.IntVar(value=1);self.orientation=tk.StringVar(value='unspecified');self.keystore=tk.StringVar();self.alias=tk.StringVar(value='upload');self.storepass=tk.StringVar();self.keypass=tk.StringVar();self.perm={k:tk.BooleanVar(value=k=='İnternet') for k in PERMISSIONS};self.make()
    def ui(self,f,*a):self.after(0,lambda:f(*a))
    def make(self):
        r=ttk.Frame(self,padding=12);r.pack(fill='both',expand=True);ttk.Label(r,text=f'APK Dönüştürücü Pro v{VERSION}',font=('Segoe UI',22,'bold')).pack(anchor='w');self.tabs=ttk.Notebook(r);self.tabs.pack(fill='both',expand=True);self.bt=ttk.Frame(self.tabs,padding=12);self.dt=ttk.Frame(self.tabs,padding=12);self.st=ttk.Frame(self.tabs,padding=12);self.at=ttk.Frame(self.tabs,padding=12);self.tabs.add(self.bt,text='Dönüştür');self.tabs.add(self.dt,text='Cihaz / Doctor');self.tabs.add(self.st,text='İmzalama');self.tabs.add(self.at,text='APK Analizi');self.make_build();self.make_tools();self.make_sign();self.make_analyze()
    def make_build(self):
        f=self.bt;s=ttk.LabelFrame(f,text='Kaynak',padding=8);s.pack(fill='x');ttk.Entry(s,textvariable=self.src).pack(side='left',fill='x',expand=True);ttk.Button(s,text='Dosya',command=self.file).pack(side='left',padx=4);ttk.Button(s,text='Klasör',command=self.folder).pack(side='left');ttk.Button(s,text='URL',command=self.url).pack(side='left',padx=4);c=ttk.LabelFrame(f,text='Ayarlar',padding=8);c.pack(fill='x',pady=8)
        for i,(lab,var) in enumerate([('Uygulama adı',self.name),('Paket adı',self.pkg),('Sürüm adı',self.version_name)]):ttk.Label(c,text=lab).grid(row=i,column=0,sticky='w');ttk.Entry(c,textvariable=var).grid(row=i,column=1,sticky='ew',padx=6,pady=2)
        ttk.Label(c,text='Sürüm kodu').grid(row=0,column=2);ttk.Spinbox(c,from_=1,to=999999,textvariable=self.version_code,width=10).grid(row=0,column=3);ttk.Label(c,text='Ekran yönü').grid(row=1,column=2);ttk.Combobox(c,textvariable=self.orientation,values=['unspecified','portrait','landscape'],state='readonly').grid(row=1,column=3);ttk.Checkbutton(c,text='HTTP izin',variable=self.http).grid(row=2,column=2);ttk.Checkbutton(c,text='Release',variable=self.release).grid(row=3,column=0);ttk.Checkbutton(c,text='AAB de oluştur',variable=self.aab).grid(row=3,column=1);c.columnconfigure(1,weight=1);p=ttk.LabelFrame(f,text='İzinler',padding=8);p.pack(fill='x')
        for i,(n,v) in enumerate(self.perm.items()):ttk.Checkbutton(p,text=n,variable=v).grid(row=i//4,column=i%4,sticky='w',padx=6)
        b=ttk.Frame(f);b.pack(fill='x',pady=8);self.go=ttk.Button(b,text='APK / AAB OLUŞTUR',command=self.start);self.go.pack(side='left');ttk.Button(b,text='Çıktıları Aç',command=lambda:os.startfile(OUTPUTS)).pack(side='left',padx=6);ttk.Button(b,text='Profil Kaydet',command=self.save_profile).pack(side='left');ttk.Button(b,text='Profil Yükle',command=self.load_profile).pack(side='left',padx=6);self.status=ttk.Label(f,text='Hazır');self.status.pack(anchor='w');self.logbox=tk.Text(f,font=('Consolas',9));self.logbox.pack(fill='both',expand=True)
    def make_tools(self):
        f=self.dt;ttk.Button(f,text='Sistem / Build Doctor',command=self.doctor).pack(anchor='w');ttk.Button(f,text='ADB Cihazları',command=self.devices).pack(anchor='w',pady=4);ttk.Button(f,text='APK Telefona Kur',command=self.install).pack(anchor='w');self.tool=tk.Text(f,font=('Consolas',10));self.tool.pack(fill='both',expand=True,pady=8)
    def make_sign(self):
        f=self.st
        for i,(lab,var,show) in enumerate([('Keystore',self.keystore,''),('Alias',self.alias,''),('Keystore parolası',self.storepass,'*'),('Anahtar parolası',self.keypass,'*')]):ttk.Label(f,text=lab).grid(row=i,column=0,sticky='w');ttk.Entry(f,textvariable=var,show=show).grid(row=i,column=1,sticky='ew',padx=6)
        ttk.Button(f,text='Keystore Seç',command=self.sel_key).grid(row=0,column=2);ttk.Button(f,text='Yeni Keystore Oluştur',command=self.make_key).grid(row=4,column=0,pady=8);ttk.Button(f,text='APK İmzasını Doğrula',command=self.verify).grid(row=4,column=1,pady=8);ttk.Label(f,text='Release seçildiğinde bilgiler doluysa APK/AAB imzalanır. Parolalar profile kaydedilmez.').grid(row=5,column=0,columnspan=3,sticky='w');f.columnconfigure(1,weight=1)
    def make_analyze(self):ttk.Button(self.at,text='APK Seç ve Analiz Et',command=self.analyze_apk).pack(anchor='w');self.apktext=tk.Text(self.at,font=('Consolas',10));self.apktext.pack(fill='both',expand=True,pady=8)
    def file(self):
        p=filedialog.askopenfilename(filetypes=[('Desteklenen','*.html *.htm *.zip *.apk'),('Tümü','*.*')]);
        if p:self.src.set(p);self.name.set(Path(p).stem)
    def folder(self):
        p=filedialog.askdirectory();
        if p:self.src.set(p);self.name.set(Path(p).name)
    def url(self):
        u=simpledialog.askstring('Web adresi','http:// veya https:// adresi:')
        if u and re.match(r'^https?://',u,re.I):self.src.set(u);self.name.set(re.sub(r'^www\.','',re.sub(r'^https?://','',u)).split('/')[0])
        elif u:messagebox.showerror('URL','Geçerli bir web adresi girin.')
    def sel_key(self):
        p=filedialog.askopenfilename(filetypes=[('Keystore','*.jks *.keystore')]);
        if p:self.keystore.set(p)
    def log(self,s):self.ui(self._log,s)
    def _log(self,s):self.logbox.insert('end',s+'\n');self.logbox.see('end')
    def doctor(self):
        j=detect_java();s=detect_sdk();lines=[f'JDK: {j or "YOK"}',f'JDK sürümü: {java_major(j) if j else "YOK"} (gereken 17)',f'Android SDK: {s or "YOK"}',f'ADB: {sdk_tool("adb") or "YOK"}',f'apksigner: {sdk_tool("apksigner") or "YOK"}']
        if s:lines += [f'API {SDK_API}: {"OK" if (s/"platforms"/f"android-{SDK_API}").exists() else "EKSİK"}',f'Build Tools {BUILD_TOOLS}: {"OK" if (s/"build-tools"/BUILD_TOOLS).exists() else "EKSİK"}'];self.tool.delete('1.0','end');self.tool.insert('end','\n'.join(lines))
    def devices(self):
        a=sdk_tool('adb');
        if not a:return messagebox.showerror('ADB','ADB bulunamadı.')
        _,o=run_capture([str(a),'devices','-l']);self.tool.delete('1.0','end');self.tool.insert('end',o)
    def install(self):
        a=sdk_tool('adb');
        if not a:return messagebox.showerror('ADB','ADB bulunamadı.')
        p=filedialog.askopenfilename(filetypes=[('APK','*.apk')]);
        if not p:return
        c,o=run_capture([str(a),'install','-r',p],timeout=180);self.tool.delete('1.0','end');self.tool.insert('end',o);messagebox.showinfo('ADB','Kurulum başarılı.' if c==0 else 'Kurulum başarısız.')
    def make_key(self):
        j=detect_java();
        if not j:return messagebox.showerror('Keystore','JDK bulunamadı.')
        out=filedialog.asksaveasfilename(defaultextension='.jks',filetypes=[('Java Keystore','*.jks')]);
        if not out:return
        alias=simpledialog.askstring('Alias','Alias:',initialvalue='upload') or 'upload';pwd=simpledialog.askstring('Parola','Parola:',show='*');
        if not pwd:return
        kt=j/'bin'/('keytool.exe' if os.name=='nt' else 'keytool');c,o=run_capture([str(kt),'-genkeypair','-v','-keystore',out,'-alias',alias,'-keyalg','RSA','-keysize','4096','-validity','10000','-storepass',pwd,'-keypass',pwd,'-dname','CN=Android Developer, OU=Mobile, O=App, C=TR'],timeout=120)
        if c:messagebox.showerror('Keystore',o[-3000:])
        else:self.keystore.set(out);self.alias.set(alias);self.storepass.set(pwd);self.keypass.set(pwd);messagebox.showinfo('Keystore','Oluşturuldu.')
    def verify(self):
        a=sdk_tool('apksigner');
        if not a:return messagebox.showerror('İmza','apksigner bulunamadı.')
        p=filedialog.askopenfilename(filetypes=[('APK','*.apk')]);
        if not p:return
        c,o=run_capture([str(a),'verify','--verbose','--print-certs',p],timeout=120);messagebox.showinfo('İmza',o[-5000:] if o else ('Geçerli' if c==0 else 'Geçersiz'))
    def analyze_apk(self):
        p=filedialog.askopenfilename(filetypes=[('APK','*.apk')]);
        if not p:return
        q=Path(p);h=hashlib.sha256();
        with q.open('rb') as f:
            for ch in iter(lambda:f.read(1024*1024),b''):h.update(ch)
        lines=[f'Dosya: {q.name}',f'Boyut: {q.stat().st_size/1024/1024:.2f} MB',f'SHA256: {h.hexdigest()}'];a=sdk_tool('aapt');
        if a:_,o=run_capture([str(a),'dump','badging',p]);lines.append(o[:10000])
        self.apktext.delete('1.0','end');self.apktext.insert('end','\n'.join(lines))
    def save_profile(self):
        p=filedialog.asksaveasfilename(initialdir=PROFILES,defaultextension='.json',filetypes=[('Profil','*.json')]);
        if not p:return
        d={'name':self.name.get(),'pkg':self.pkg.get(),'version_name':self.version_name.get(),'version_code':self.version_code.get(),'orientation':self.orientation.get(),'http':self.http.get(),'release':self.release.get(),'aab':self.aab.get(),'keystore':self.keystore.get(),'alias':self.alias.get(),'permissions':[k for k,v in self.perm.items() if v.get()]};Path(p).write_text(json.dumps(d,ensure_ascii=False,indent=2),encoding='utf-8')
    def load_profile(self):
        p=filedialog.askopenfilename(initialdir=PROFILES,filetypes=[('Profil','*.json')]);
        if not p:return
        try:d=json.loads(Path(p).read_text(encoding='utf-8'))
        except Exception as e:return messagebox.showerror('Profil',str(e))
        self.name.set(d.get('name','Uygulamam'));self.pkg.set(d.get('pkg','com.apkkurucu.uygulamam'));self.version_name.set(d.get('version_name','1.0'));self.version_code.set(d.get('version_code',1));self.orientation.set(d.get('orientation','unspecified'));self.http.set(d.get('http',False));self.release.set(d.get('release',False));self.aab.set(d.get('aab',False));self.keystore.set(d.get('keystore',''));self.alias.set(d.get('alias','upload'))
        for k,v in self.perm.items():v.set(k in d.get('permissions',[]))
    def start(self):
        if self.building:return messagebox.showinfo('Derleme','Bir derleme zaten devam ediyor.')
        self.building=True;self.go.configure(state='disabled');self.status.configure(text='Derleniyor...');threading.Thread(target=self.worker,daemon=True).start()
    def done(self):self.building=False;self.go.configure(state='normal');self.status.configure(text='Hazır')
    def worker(self):
        try:
            src=self.src.get().strip();
            if not src:raise RuntimeError('Kaynak seçilmedi.')
            j=detect_java();s=detect_sdk();
            if not j:raise RuntimeError('JDK bulunamadı. JDK 17 veya Android Studio kurun.')
            if java_major(j)!=17:raise RuntimeError(f'JDK 17 gerekli. Bulunan sürüm: {java_major(j)}')
            if not s:raise RuntimeError('Android SDK bulunamadı.')
            ensure_sdk(s,j,self.log);g=ensure_gradle(self.log);stamp=time.strftime('%Y%m%d_%H%M%S');project=BUILDS/f'build_{stamp}';project.mkdir();pkg=normalize_pkg(self.pkg.get());per=[PERMISSIONS[k] for k,v in self.perm.items() if v.get()];url=bool(re.match(r'^https?://',src,re.I));root=None;sign=None
            if self.release.get() and self.keystore.get():
                if not Path(self.keystore.get()).exists():raise RuntimeError('Keystore bulunamadı.')
                if not self.storepass.get():raise RuntimeError('Release imzalama için parola gerekli.')
                sign=(self.keystore.get(),self.alias.get() or 'upload',self.storepass.get(),self.keypass.get() or self.storepass.get())
            if url:html_project(None,project,self.name.get(),pkg,self.http.get(),per,url=src,version_name=self.version_name.get(),version_code=self.version_code.get(),orientation=self.orientation.get(),signing=sign);root=project
            else:
                p=Path(src)
                if not p.exists():raise RuntimeError('Kaynak bulunamadı.')
                if p.suffix.lower()=='.apk':raise RuntimeError('APK kaynak olarak derlenmez; APK Analizi sekmesini kullanın.')
                if p.is_dir() and find_root(p):shutil.copytree(p,project,dirs_exist_ok=True);root=find_root(project)
                elif p.suffix.lower()=='.zip':
                    probe=project/'probe';probe.mkdir();safe_extract(p,probe);ar=find_root(probe)
                    if ar:root=ar
                    else:shutil.rmtree(probe);html_project(p,project,self.name.get(),pkg,self.http.get(),per,version_name=self.version_name.get(),version_code=self.version_code.get(),orientation=self.orientation.get(),signing=sign);root=project
                else:html_project(p,project,self.name.get(),pkg,self.http.get(),per,version_name=self.version_name.get(),version_code=self.version_code.get(),orientation=self.orientation.get(),signing=sign);root=project
            env=os.environ.copy();env.update(JAVA_HOME=str(j),ANDROID_HOME=str(s),ANDROID_SDK_ROOT=str(s));wrap=root/('gradlew.bat' if os.name=='nt' else 'gradlew');exe=wrap if wrap.exists() else g;tasks=['assembleRelease' if self.release.get() else 'assembleDebug']+([('bundleRelease' if self.release.get() else 'bundleDebug')] if self.aab.get() else [])
            for t in tasks:
                self.log('Derleniyor: '+t)
                if run_build([str(exe),t,'--stacktrace'],root,env,self.log):raise RuntimeError('Gradle görevi başarısız: '+t)
            arts=[x for x in root.rglob('*') if x.suffix.lower() in ('.apk','.aab') and 'outputs' in x.parts]
            if not arts:raise RuntimeError('APK/AAB bulunamadı.')
            out=OUTPUTS/f"{re.sub(r'[^A-Za-z0-9_-]','_',self.name.get())}_{stamp}";out.mkdir();cop=[];sig=sdk_tool('apksigner')
            for x in arts:
                d=out/x.name;shutil.copy2(x,d);cop.append(d)
                if d.suffix.lower()=='.apk' and self.release.get() and sign and sig:
                    c,o=run_capture([str(sig),'verify','--verbose','--print-certs',str(d)],timeout=120);self.log('İmza doğrulama: '+('BAŞARILI' if c==0 else 'BAŞARISIZ'))
                    if c:raise RuntimeError('Release APK imza doğrulaması başarısız.')
            self.ui(messagebox.showinfo,'Tamamlandı','Hazır:\n'+'\n'.join(map(str,cop)))
        except Exception as e:self.log('HATA: '+str(e));self.ui(messagebox.showerror,'Hata',str(e))
        finally:self.ui(self.done)

if __name__=='__main__':App().mainloop()
