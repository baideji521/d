param(
    [string]$TextPath = "",
    [string]$OutPath = "",
    [string]$VoiceName = "",
    [int]$Rate = 0,
    [int]$Volume = 100,
    [switch]$ListVoices
)

# 文本转语音：用 Windows 自带的 System.Speech 离线合成 WAV。
# 不联网、不需要 API Key，也不需要 pip 安装任何东西。
# 待读文本走文件传入（UTF-8），避免命令行引号转义和中文编码问题。

$ErrorActionPreference = "Stop"

try {
    Add-Type -AssemblyName System.Speech

    if ($ListVoices) {
        $probe = New-Object System.Speech.Synthesis.SpeechSynthesizer
        foreach ($v in $probe.GetInstalledVoices()) {
            if (-not $v.Enabled) { continue }
            $info = $v.VoiceInfo
            Write-Output ("{0}`t{1}`t{2}" -f $info.Name, $info.Culture.Name, $info.Gender)
        }
        $probe.Dispose()
        exit 0
    }

    if ([string]::IsNullOrWhiteSpace($TextPath) -or [string]::IsNullOrWhiteSpace($OutPath)) {
        Write-Error "TTS_MISSING_ARGS"
        exit 2
    }

    $text = [System.IO.File]::ReadAllText($TextPath, [System.Text.Encoding]::UTF8)
    if ([string]::IsNullOrWhiteSpace($text)) {
        Write-Error "TTS_EMPTY_TEXT"
        exit 2
    }

    $synth = New-Object System.Speech.Synthesis.SpeechSynthesizer
    if (-not [string]::IsNullOrWhiteSpace($VoiceName)) {
        $synth.SelectVoice($VoiceName)
    }
    $synth.Rate = [Math]::Max(-10, [Math]::Min(10, $Rate))
    $synth.Volume = [Math]::Max(0, [Math]::Min(100, $Volume))

    $dir = [System.IO.Path]::GetDirectoryName($OutPath)
    if (-not [string]::IsNullOrEmpty($dir)) {
        [void][System.IO.Directory]::CreateDirectory($dir)
    }

    $synth.SetOutputToWaveFile($OutPath)
    $synth.Speak($text)
    $synth.SetOutputToNull()
    $synth.Dispose()
    Write-Output "TTS_OK"
    exit 0
}
catch {
    Write-Error $_.Exception.Message
    exit 1
}
