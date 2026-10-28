using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;
using ModelContextProtocol.Server;

var configPath = ResolveConfigPath(args);
var profileStore = ProfileStore.Load(configPath);
McpRuntime.Profiles = profileStore;

var builder = Host.CreateApplicationBuilder([]);
builder.Logging.ClearProviders();
builder.Logging.AddConsole(options => options.LogToStandardErrorThreshold = LogLevel.Trace);
builder.Services
    .AddMcpServer()
    .WithStdioServerTransport()
    .WithToolsFromAssembly();

var app = builder.Build();
try
{
    await app.RunAsync();
}
finally
{
    UnrealAssetTools.DisposeProviders();
}

static string ResolveConfigPath(string[] args)
{
    for (var i = 0; i < args.Length; i++)
    {
        if (args[i] is "--config" or "-c" && i + 1 < args.Length)
            return Path.GetFullPath(args[i + 1]);
    }

    var env = Environment.GetEnvironmentVariable("CUE4PARSE_MCP_CONFIG");
    if (!string.IsNullOrWhiteSpace(env)) return Path.GetFullPath(env);

    var local = Path.Combine(AppContext.BaseDirectory, "games.json");
    return File.Exists(local) ? local : Path.Combine(Environment.CurrentDirectory, "games.json");
}


