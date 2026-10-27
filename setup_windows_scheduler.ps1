$Action = New-ScheduledTaskAction -Execute "pythonw.exe" -Argument "main.py --sync-once" -WorkingDirectory "$PSScriptRoot"
$Trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 30)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

Register-ScheduledTask -TaskName "PassthruClipSync" -Action $Action -Trigger $Trigger -Settings $Settings -Description "Automated SteelSeries Moments clip sync to Google Drive with rolling storage limit." -Force

Write-Host "Scheduled Task 'PassthruClipSync' created successfully! It will run silently every 30 minutes in the background." -ForegroundColor Green
