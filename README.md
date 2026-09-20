# GitHub Release annual BIN → Hugging Face daily BIN

این پروژه فایل ZIP سالانه را از GitHub Release دانلود می‌کند، فایل BIN داخل آن را بر اساس timestampهای UTC به فایل‌های روزانه تقسیم می‌کند و کل روزهای هر ZIP را با یک batch در Hugging Face آپلود می‌کند.

## فرمت پشتیبانی‌شده

همان `bin_v1` پروژه BarReplay:

```text
uint32 tick_count (little-endian)
int64[tick_count] timestamp_ms
float64[tick_count] bid
float64[tick_count] ask
```

فایل سالانه باید از اتصال blockهای ساعتی همین فرمت ساخته شده باشد.

## فایل‌های پروژه

```text
.github/workflows/migrate-release-bin-to-hf.yml
tools/split_yearly_bin.py
tools/upload_daily_hf.py
```

## تنظیم GitHub

در repository مقصد Workflow این موارد را بسازید:

- Secret: `HF_TOKEN`
- Variable: `HF_DATASET`، مثلاً `Esmaeil9ss/Tickdata`
- فقط برای Release خصوصی یا repository دیگری که `GITHUB_TOKEN` به آن دسترسی ندارد:
  Secret: `SOURCE_GH_TOKEN`

## اجرای Workflow

از Actions، Workflow با نام زیر را اجرا کنید:

```text
Migrate annual Release BIN files to Hugging Face
```

ورودی‌ها:

- `source_repo`: مانند `forexdata/XAUUSD`
- `release_tag`: نام tag یا `latest`
- `asset_pattern`: مانند `XAUUSD_*.zip`
- `symbol`: مانند `XAUUSD`
- `digits`: تعداد رقم اعشار در `index.txt`

هر ZIP باید دقیقاً یک فایل `.BIN` سالانه داشته باشد. چند ZIP منطبق با pattern به‌ترتیب پردازش می‌شوند. پس از هر ZIP، فایل‌های روزانه همان سال یک‌جا آپلود و فایل‌های موقت پاک می‌شوند.

## خروجی

```text
XAUUSD/XAUUSD_2023-01-01.BIN
XAUUSD/XAUUSD_2023-01-02.BIN
...
index.txt
```

Workflow فایل‌های موجود با همان نام و اندازه را دوباره آپلود نمی‌کند و `index.txt` فعلی Hugging Face را با اطلاعات جدید ادغام می‌کند.
