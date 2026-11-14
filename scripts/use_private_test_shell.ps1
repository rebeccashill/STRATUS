# Dot-source before long local checks in the bundled PowerShell test shell.
# Suppress only this process's optional startup diagnostics; leave system
# security logging, network isolation and approval controls unchanged.
$env:POWERSHELL_TELEMETRY_OPTOUT = '1'
& {
    $ErrorActionPreference = 'Stop'
    $telemetryType = [System.Management.Automation.PowerShell].Assembly.GetType('Microsoft.PowerShell.Telemetry.ApplicationInsightsTelemetry')
    if ($null -eq $telemetryType) { return }
    $field = $telemetryType.GetField('<s_telemetryClient>k__BackingField', [System.Reflection.BindingFlags]'Static,NonPublic')
    if ($null -eq $field) { throw 'This PowerShell build needs its diagnostic adapter reviewed before running checks.' }
    $client = $field.GetValue($null)
    if ($null -eq $client) { return }
    $client.TelemetryConfiguration.DisableTelemetry = $true
    $client.TelemetryConfiguration.TelemetryChannel.EndpointAddress = 'http://127.0.0.1:0/'
    if (-not $client.TelemetryConfiguration.DisableTelemetry -or $client.TelemetryConfiguration.TelemetryChannel.EndpointAddress -ne 'http://127.0.0.1:0/') {
        throw 'Optional diagnostic sender was not suppressed.'
    }
}
