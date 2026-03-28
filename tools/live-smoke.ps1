param(
  [string]$BaseUrl = "https://gaia-magnetics-348555315681.us-central1.run.app"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Net.Http

function Write-Step([string]$Message) {
  Write-Host ("== {0} ==" -f $Message)
}

function Invoke-Json([string]$Method, [string]$Url, [object]$Body = $null) {
  if ($null -eq $Body) {
    return Invoke-RestMethod -Uri $Url -Method $Method
  }
  return Invoke-RestMethod -Uri $Url -Method $Method -ContentType "application/json" -Body ($Body | ConvertTo-Json -Depth 8)
}

Write-Step "health"
$health = Invoke-Json "Get" "$BaseUrl/api/health"
$health | ConvertTo-Json -Compress | Write-Host

Write-Step "create project"
$project = Invoke-Json "Post" "$BaseUrl/api/projects" @{
  name = "GAIA Live Smoke"
  context = "Ground magnetic survey over a compact test area to verify live upload, preview, processing, maps, Aurora, and export."
}
$project | ConvertTo-Json -Compress | Write-Host

Write-Step "upload task"
$csv = @'
latitude,longitude,magnetic
6.5244,3.3792,41250
6.5248,3.3796,41268
6.5252,3.3800,41281
6.5256,3.3804,41295
6.5260,3.3808,41310
6.5264,3.3812,41308
6.5268,3.3816,41296
6.5272,3.3820,41285
6.5276,3.3824,41274
6.5280,3.3828,41260
'@
$bytes = [System.Text.Encoding]::UTF8.GetBytes($csv)
$client = New-Object System.Net.Http.HttpClient
$client.Timeout = [TimeSpan]::FromSeconds(90)
$multipart = [System.Net.Http.MultipartFormDataContent]::new()
$fields = @{
  name = "GAIA Live Smoke Task"
  description = "Single-line upload validation task."
  platform = "ground"
  data_state = "raw"
  scenario = "explicit"
  processing_mode = "single"
  station_spacing = "25"
  station_spacing_unit = "Metres"
  corrected_corrections = "[]"
  column_mapping = '{"latitude":"latitude","longitude":"longitude","magnetic_field":"magnetic"}'
  metadata = '{"headers":["latitude","longitude","magnetic"]}'
}
foreach ($entry in $fields.GetEnumerator()) {
  $multipart.Add([System.Net.Http.StringContent]::new($entry.Value), $entry.Key)
}
$fileContent = [System.Net.Http.ByteArrayContent]::new($bytes)
$fileContent.Headers.ContentType = [System.Net.Http.Headers.MediaTypeHeaderValue]::Parse("text/csv")
$multipart.Add($fileContent, "survey_files", "live-smoke.csv")
$response = $client.PostAsync("$BaseUrl/api/projects/$($project.id)/tasks", $multipart).GetAwaiter().GetResult()
$taskBody = $response.Content.ReadAsStringAsync().GetAwaiter().GetResult()
[PSCustomObject]@{
  StatusCode = [int]$response.StatusCode
  Body = $taskBody
} | ConvertTo-Json -Compress | Write-Host
if (-not $response.IsSuccessStatusCode) {
  throw "Task upload failed."
}
$task = $taskBody | ConvertFrom-Json

Write-Step "save analysis"
$analysis = Invoke-Json "Put" "$BaseUrl/api/projects/$($project.id)/tasks/$($task.id)/analysis" @{
  corrections = @("diurnal", "igrf")
  filter_type = "low-pass"
  model = "hybrid"
  add_ons = @("analytic_signal", "uncertainty")
  run_prediction = $true
}
$analysis | ConvertTo-Json -Compress | Write-Host

Write-Step "preview"
$preview = Invoke-Json "Get" "$BaseUrl/api/projects/$($project.id)/tasks/$($task.id)/preview"
$preview.aurora | ConvertTo-Json -Compress | Write-Host

Write-Step "processing"
$run = Invoke-Json "Post" "$BaseUrl/api/processing/tasks/$($task.id)/runs"
$run | ConvertTo-Json -Compress | Write-Host

for ($i = 0; $i -lt 30; $i++) {
  Start-Sleep -Seconds 3
  $poll = Invoke-Json "Get" "$BaseUrl/api/processing/runs/$($run.id)"
  Write-Host ("poll={0} status={1}" -f $i, $poll.status)
  if ($poll.status -in @("completed", "failed")) {
    break
  }
}
if ($poll.status -ne "completed") {
  throw "Processing did not complete."
}

Write-Step "aurora"
$aurora = Invoke-Json "Post" "$BaseUrl/api/ai/respond" @{
  project_id = $project.id
  task_id = $task.id
  location = "visualisation"
  question = "Summarise the processed anomaly pattern."
}
$aurora | ConvertTo-Json -Compress | Write-Host

Write-Step "export"
$export = Invoke-Json "Post" "$BaseUrl/api/exports/tasks/$($task.id)" @{
  formats = @("pdf", "csv", "png")
  aurora_sections = @("Anomaly catalogue", "Structural interpretation")
}
$export | ConvertTo-Json -Compress | Write-Host

Write-Step "done"
