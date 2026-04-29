# Edge WebView2 Blocker

`msedgewebview2_blocker.py`는 `msedgewebview2.exe`가 실행되는지 계속 감시하다가, 발견되면 즉시 종료하는 Windows용 차단기입니다.

## 기능

- `msedgewebview2.exe` 감시
- 프로세스가 뜨면 즉시 강제 종료
- 중복 실행 방지
- `%LOCALAPPDATA%\EdgeWebView2Blocker` 아래에 로그와 PID 파일 저장

## Python으로 실행

```powershell
python .\msedgewebview2_blocker.py
```

자주 쓰는 옵션:

```powershell
python .\msedgewebview2_blocker.py --status
python .\msedgewebview2_blocker.py --stop
python .\msedgewebview2_blocker.py --interval 0.3
```

## EXE 빌드

```powershell
pyinstaller --onefile --name EdgeWebView2Blocker .\msedgewebview2_blocker.py
```

빌드 결과물 위치:

`dist\EdgeWebView2Blocker.exe`

## 주의

WebView2는 일부 Microsoft 앱과 Windows 기능에서 내부적으로 사용됩니다. 그래서 `msedgewebview2.exe`를 차단하면 로그인 창, 내장 웹 화면, 앱 일부 기능이 정상 동작하지 않을 수 있습니다.
