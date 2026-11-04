# PRP-27 offline narration: Windows built-in System.Speech, no network, no paid service.
# PowerShell 5.1 safe, pure ASCII. Usage:
#   powershell -NoProfile -ExecutionPolicy Bypass -File speak.ps1 -TextFile in.txt -OutWav out.wav
param(
    [Parameter(Mandatory = $true)][string]$TextFile,
    [Parameter(Mandatory = $true)][string]$OutWav,
    [string]$Voice = "Microsoft Zira Desktop"
)
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$text = [System.IO.File]::ReadAllText($TextFile, [System.Text.Encoding]::UTF8)
$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $synth.SelectVoice($Voice)
    $synth.SetOutputToWaveFile($OutWav)
    $synth.Speak($text)
}
finally {
    $synth.Dispose()
}
