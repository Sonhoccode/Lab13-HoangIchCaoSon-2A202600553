# Day 13 Lab Observathon - Run And Score

Huong dan nay dung cho Windows PowerShell va chay binary Linux bang Docker. Khong chay truc tiep file `.exe` neu gap loi PyInstaller/Python DLL.

## 1. Dieu kien truoc khi chay

Dung PowerShell tai thu muc project:

```powershell
cd "C:\Users\H Son\Documents\Code\VinUni-ThucChienAI\Day-13-Lab-Observathon"
```

Kiem tra Docker image:

```powershell
docker images observathon-runner
```

Neu chua co image, build:

```powershell
docker build -f Dockerfile.observathon -t observathon-runner .
```

Set OpenAI API key trong dung terminal dang chay:

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

Kiem tra key tren host:

```powershell
if ([string]::IsNullOrWhiteSpace($env:OPENAI_API_KEY)) { "MISSING" } else { "SET" }
```

Kiem tra Docker nhan duoc key:

```powershell
docker run --rm -e OPENAI_API_KEY observathon-runner bash -lc 'if [ -z "$OPENAI_API_KEY" ]; then echo MISSING; else echo SET; fi'
```

Chi chay simulator khi ca hai lenh tren deu ra:

```text
SET
```

## 2. Selfcheck truoc khi chay

```powershell
python .\harness\selfcheck.py
```

Ket qua mong muon:

```text
READY to run the scorer + push.
```

Neu fail, sua file trong `solution/` truoc khi chay score.

## 3. Chay Public Sim

Xoa output cu:

```powershell
Remove-Item .\run_output.json -ErrorAction SilentlyContinue
Remove-Item .\score.json -ErrorAction SilentlyContinue
Remove-Item .\solution\telemetry.jsonl -ErrorAction SilentlyContinue
```

Chay public simulator:

```powershell
docker run --rm -e OPENAI_API_KEY -v "C:\Users\H Son\Documents\Code\VinUni-ThucChienAI\Day-13-Lab-Observathon:/lab" observathon-runner bash -lc "cd /lab && chmod +x bin/public/observathon-sim && ./bin/public/observathon-sim --config solution/config.json --wrapper solution/wrapper.py --out run_output.json"
```

Chi duoc chay score neu output co dang:

```text
[observathon-sim] ran 120 requests -> run_output.json  (status ok=120)
```

Neu `ok` nho hon `120`, khong chay score. Kiem tra loi:

```powershell
Get-Content .\solution\telemetry.jsonl -Tail 40
```

## 4. Cham Public Score

```powershell
docker run --rm -v "C:\Users\H Son\Documents\Code\VinUni-ThucChienAI\Day-13-Lab-Observathon:/lab" observathon-runner bash -lc "cd /lab && chmod +x bin/public/observathon-score && ./bin/public/observathon-score --run run_output.json --findings solution/findings.json --team hson --out score.json"
```

Doc ket qua:

```powershell
Get-Content .\score.json
```

Public score chi dung de tuning. Ket qua cu da tung dat `100/100`, nhung phai chay lai sau moi lan sua `solution/`.

## 5. Chay Private Sim

Xoa output cu:

```powershell
Remove-Item .\run_output.json -ErrorAction SilentlyContinue
Remove-Item .\score.json -ErrorAction SilentlyContinue
Remove-Item .\solution\telemetry.jsonl -ErrorAction SilentlyContinue
```

Chay private simulator:

```powershell
docker run --rm -e OPENAI_API_KEY -v "C:\Users\H Son\Documents\Code\VinUni-ThucChienAI\Day-13-Lab-Observathon:/lab" observathon-runner bash -lc "cd /lab && chmod +x bin/private/observathon-sim && ./bin/private/observathon-sim --config solution/config.json --wrapper solution/wrapper.py --out run_output.json"
```

Chi duoc chay score neu output co dang:

```text
[observathon-sim] ran 80 requests -> run_output.json  (status ok=80)
```

Neu thay `wrapper_error`, `AuthenticationError`, hoac `sk-none`, dung lai. Kiem tra:

```powershell
python -c "import json,collections; d=json.load(open('run_output.json',encoding='utf-8')); print(collections.Counter(r.get('status') for r in d['results'])); print(d['results'][:5])"
Get-Content .\solution\telemetry.jsonl -Tail 40
```

## 6. Cham Private Score

```powershell
docker run --rm -v "C:\Users\H Son\Documents\Code\VinUni-ThucChienAI\Day-13-Lab-Observathon:/lab" observathon-runner bash -lc "cd /lab && chmod +x bin/private/observathon-score && ./bin/private/observathon-score --run run_output.json --findings solution/findings.json --team hson --out score.json"
```

Doc ket qua:

```powershell
Get-Content .\score.json
```

Private la diem nop cuoi. Sau khi co diem tot, khong chay lai neu khong can thiet vi private sim co the bi anh huong boi loi tool/LLM trong lan moi.

## 7. Cac loi thuong gap

### Score ra 0 correct

Kiem tra `run_output.json`:

```powershell
python -c "import json,collections; d=json.load(open('run_output.json',encoding='utf-8')); print(collections.Counter(r.get('status') for r in d['results']))"
```

Neu co `wrapper_error`, xem telemetry:

```powershell
Get-Content .\solution\telemetry.jsonl -Tail 40
```

Neu thay `sk-none` hoac `AuthenticationError`, nghia la Docker khong nhan API key. Set lai:

```powershell
$env:OPENAI_API_KEY = "sk-..."
```

### Score bao public 0 q khi dang cham private

Ban dang dung sai scorer. Private phai dung:

```text
bin/private/observathon-score
```

Public phai dung:

```text
bin/public/observathon-score
```

Khong dung `bin/observathon-score` neu repo cua ban da co scorer rieng trong `bin/public` va `bin/private`.

### Docker khong thay file binary

Kiem tra dung path trong container:

```powershell
docker run --rm -v "C:\Users\H Son\Documents\Code\VinUni-ThucChienAI\Day-13-Lab-Observathon:/lab" observathon-runner bash -lc "cd /lab && ls -lh bin/public bin/private"
```

### Chay qua lau

Dung public/private score thi khong them `--users`, `--turns`, `--rps`. Chay mac dinh de dung bo cham:

```text
public: 120 requests
private: 80 requests
```

## 8. File can nop

Sau khi da co score tot:

```text
solution/config.json
solution/prompt.txt
solution/examples.json
solution/wrapper.py
solution/findings.json
solution/telemetry.jsonl
run_output.json
score.json
```

Commit:

```powershell
git add solution run_output.json score.json README.md Dockerfile.observathon
git commit -m "final observathon score"
git push
```

