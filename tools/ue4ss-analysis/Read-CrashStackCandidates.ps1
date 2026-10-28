param([Parameter(Mandatory=$true)][string]$DumpPath)
$ErrorActionPreference = 'Stop'
Write-Output "[$(Get-Date -Format 'dd-MM-yyyy HH:mm:ss')] Begin read-only minidump stack candidate inspection"
$file = [IO.File]::OpenRead($DumpPath)
$reader = [IO.BinaryReader]::new($file)
try {
    if ($reader.ReadUInt32() -ne 0x504D444D) { throw 'Not a minidump' }
    $file.Position = 8
    $streamCount = $reader.ReadUInt32()
    $directory = $reader.ReadUInt32()
    $streams = @{}
    for ($i=0; $i -lt $streamCount; $i++) {
        $file.Position = $directory + 12L*$i
        $type = $reader.ReadUInt32()
        $size = $reader.ReadUInt32()
        $rva = $reader.ReadUInt32()
        $streams[$type] = $rva
    }
    $file.Position = $streams[[uint32]6] + 160L
    $contextSize = $reader.ReadUInt32()
    $contextRva = $reader.ReadUInt32()
    if ($contextSize -lt 256) { throw 'x64 context too small' }
    $file.Position = $contextRva + 152L
    $rsp = $reader.ReadUInt64()
    $file.Position = $streams[[uint32]4]
    $moduleCount = $reader.ReadUInt32()
    $modules = @()
    for ($i=0; $i -lt $moduleCount; $i++) {
        $file.Position = $streams[[uint32]4] + 4L + 108L*$i
        $base = $reader.ReadUInt64()
        $size = $reader.ReadUInt32()
        $file.Position += 8
        $nameRva = $reader.ReadUInt32()
        $file.Position = $nameRva
        $length = $reader.ReadUInt32()
        if ($length -gt 8192) { throw 'Unexpected module name length' }
        $name = [Text.Encoding]::Unicode.GetString($reader.ReadBytes($length))
        $modules += [pscustomobject]@{Base=$base;Size=$size;Name=$name}
    }
    $stackPosition = $null
    $available = 0
    foreach ($type in @([uint32]9,[uint32]5)) {
        if (!$streams.ContainsKey($type)) { continue }
        $file.Position = $streams[$type]
        if ($type -eq 9) {
            $count = $reader.ReadUInt64()
            $data = $reader.ReadUInt64()
            $header = 16
        } else {
            $count = $reader.ReadUInt32()
            $header = 4
            $data = 0L
        }
        for ($i=0; $i -lt $count; $i++) {
            $file.Position = $streams[$type] + $header + 16L*$i
            $start = $reader.ReadUInt64()
            if ($type -eq 9) {
                $size = $reader.ReadUInt64()
            } else {
                $size = $reader.ReadUInt32()
                $data = $reader.ReadUInt32()
            }
            if ($rsp -ge $start -and $rsp -lt $start+$size) {
                $stackPosition = [long]($data+$rsp-$start)
                $available = $size-($rsp-$start)
                break
            }
            if ($type -eq 9) { $data += $size }
        }
        if ($null -ne $stackPosition) { break }
    }
    if ($null -eq $stackPosition) { throw 'No memory descriptor covers RSP' }
    Write-Output ('RSP=0x{0:X}; dump file offset=0x{1:X}. These are stack words, NOT an unwound call stack.' -f $rsp,$stackPosition)
    for ($i=0; $i -lt 96 -and 8*$i+8 -le $available; $i++) {
        $file.Position = $stackPosition+8*$i
        $value = $reader.ReadUInt64()
        foreach ($module in $modules) {
            if ($value -ge $module.Base -and $value -lt $module.Base+$module.Size) {
                [pscustomobject]@{
                    StackOffset = ('0x{0:X}' -f (8*$i))
                    Address = ('0x{0:X16}' -f $value)
                    Module = [IO.Path]::GetFileName($module.Name)
                    Rva = ('0x{0:X}' -f ($value-$module.Base))
                }
                break
            }
        }
    }
} finally {
    $reader.Dispose()
    $file.Dispose()
    Write-Output "[$(Get-Date -Format 'dd-MM-yyyy HH:mm:ss')] End read-only minidump stack candidate inspection"
}
