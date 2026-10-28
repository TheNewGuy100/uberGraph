import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline';

const [dotnet, assembly, config] = process.argv.slice(2);
if (!dotnet || !assembly || !config) {
  console.error('Usage: node mcp-smoke.mjs <dotnet.exe> <server.dll> <games.local.json>');
  process.exit(2);
}

const child = spawn(dotnet, [assembly, '--config', config], { stdio: ['pipe', 'pipe', 'pipe'] });
const lines = createInterface({ input: child.stdout });
const pending = new Map();
let nextId = 1;
lines.on('line', line => {
  try {
    const message = JSON.parse(line);
    if (message.id && pending.has(message.id)) {
      pending.get(message.id)(message);
      pending.delete(message.id);
    }
  } catch {
    console.error(`Non-JSON stdout from MCP server: ${line}`);
  }
});
child.stderr.on('data', chunk => process.stderr.write(chunk));

function rpc(method, params = {}) {
  const id = nextId++;
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pending.delete(id);
      reject(new Error(`Timed out waiting for ${method}`));
    }, 15000);
    pending.set(id, message => {
      clearTimeout(timer);
      if (message.error) reject(new Error(JSON.stringify(message.error)));
      else resolve(message.result);
    });
    child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', id, method, params })}\n`);
  });
}

try {
  const initialized = await rpc('initialize', {
    protocolVersion: '2025-11-25',
    capabilities: {},
    clientInfo: { name: 'cue4parse-mcp-smoke', version: '0.1.0' }
  });
  child.stdin.write(`${JSON.stringify({ jsonrpc: '2.0', method: 'notifications/initialized' })}\n`);
  const tools = await rpc('tools/list');
  const names = tools.tools.map(tool => tool.name);
  console.log(JSON.stringify({ protocolVersion: initialized.protocolVersion, tools: names }, null, 2));

  const listTool = names.find(name => name.includes('list_game_profiles'));
  const inventoryTool = names.find(name => name.includes('inventory_containers'));
  if (!listTool || !inventoryTool) throw new Error('Expected profile and container inventory tools were not registered.');
  const profileResult = await rpc('tools/call', { name: listTool, arguments: {} });
  const inventoryResult = await rpc('tools/call', { name: inventoryTool, arguments: { profileId: 'the-last-caretaker', limit: 100 } });
  const loadTool = names.find(name => name.includes('load_game_profile'));
  const loadResult = await rpc('tools/call', { name: loadTool, arguments: { profileId: 'the-last-caretaker' } });
  const searchTool = names.find(name => name.includes('search_assets'));
  const sampleSearches = {};
  for (const query of ['BP_', 'DA_', 'DataAsset', 'Blueprint']) {
    sampleSearches[query] = await rpc('tools/call', { name: searchTool, arguments: { profileId: 'the-last-caretaker', query, limit: 12, pathPrefix: 'Voyage/Content/' } });
  }
  sampleSearches['paged-offset'] = await rpc('tools/call', { name: searchTool, arguments: { profileId: 'the-last-caretaker', query: 'BP_', limit: 2, offset: 2, pathPrefix: 'Voyage/Content/Animations/Notify/' } });
  sampleSearches['assetName-filter'] = await rpc('tools/call', { name: searchTool, arguments: { profileId: 'the-last-caretaker', query: 'BP_', limit: 10, assetName: 'Dropped_Magazine' } });
  sampleSearches['extension-filter'] = await rpc('tools/call', { name: searchTool, arguments: { profileId: 'the-last-caretaker', query: 'BP_', limit: 3, extension: '.uasset' } });
  sampleSearches['DT_'] = await rpc('tools/call', { name: searchTool, arguments: { profileId: 'the-last-caretaker', query: 'DT_', limit: 8, pathPrefix: 'Voyage/Content/' } });
  sampleSearches['M_'] = await rpc('tools/call', { name: searchTool, arguments: { profileId: 'the-last-caretaker', query: 'M_', limit: 8, pathPrefix: 'Voyage/Content/' } });
  const inspectTool = names.find(name => name.includes('inspect_asset'));
  const sampleInspections = {};
  for (const packagePath of [
    'Voyage/Content/Animations/Notify/BP_Dropped_Magazine.uasset',
    'Voyage/Content/Blueprints/Subsystems/DA_WorldSpawnData.uasset',
    'Voyage/Content/Data/GameProgress/DT_VoyageCharacterLevels.uasset',
    'Voyage/Content/AdvancedGlassPack/Materials/05_Wet/M_Glass_WetMaster.uasset'
  ]) {
    sampleInspections[packagePath] = await rpc('tools/call', { name: inspectTool, arguments: { profileId: 'the-last-caretaker', packagePath, maxExports: 12 } });
  }
  sampleInspections['index-only-blueprint'] = await rpc('tools/call', { name: inspectTool, arguments: { profileId: 'the-last-caretaker', packagePath: 'Voyage/Content/Animations/Notify/BP_Dropped_Magazine.uasset', load: false } });
  const diagnosticTool = names.find(name => name.includes('diagnose_io_store'));
  const diagnosticResult = diagnosticTool ? await rpc('tools/call', { name: diagnosticTool, arguments: { profileId: 'the-last-caretaker' } }) : null;
  const validateMappingsTool = names.find(name => name.includes('validate_mappings'));
  const mappingValidationResult = validateMappingsTool
    ? await rpc('tools/call', { name: validateMappingsTool, arguments: { profileId: 'the-last-caretaker' } })
    : null;
  const discoverSubsystemsTool = names.find(name => name.includes('discover_subsystems'));
  const subsystemDiscoveryResult = discoverSubsystemsTool
    ? await rpc('tools/call', { name: discoverSubsystemsTool, arguments: { profileId: 'the-last-caretaker', pathPrefix: 'Voyage/Content/', offset: 0, limit: 5 } })
    : null;
  const validateCatalogTool = names.find(name => name.includes('validate_asset_catalog'));
  const catalogValidationResult = validateCatalogTool
    ? await rpc('tools/call', { name: validateCatalogTool, arguments: { profileId: 'the-last-caretaker' } })
    : null;
  const decode = result => {
    const text = result?.content?.find(item => item.type === 'text')?.text;
    if (!text) return result;
    try { return JSON.parse(text); } catch { return text; }
  };
  const searchSummaries = Object.fromEntries(Object.entries(sampleSearches).map(([key, result]) => {
    const value = decode(result);
    return [key, { countReturned: value?.countReturned, hasMore: value?.hasMore, nextOffset: value?.nextOffset, paths: value?.results?.map(item => item.path) ?? value }];
  }));
  const inspectionSummaries = Object.fromEntries(Object.entries(sampleInspections).map(([key, result]) => {
    const value = decode(result);
    return [key, { path: value?.path ?? value?.asset?.path, status: value?.status, stage: value?.stage, exceptionType: value?.exceptionType, exception: value?.exception?.split('\n')[0], propertyCount: value?.properties?.length, logEventCount: value?.cue4parseLogEventCount }];
  }));
  const extensionPaths = searchSummaries['extension-filter'].paths;
  if (!extensionPaths.length || extensionPaths.some(path => !path.toLowerCase().endsWith('.uasset'))) {
    throw new Error(`Extension filter did not return only .uasset paths: ${JSON.stringify(extensionPaths)}`);
  }
  if (searchSummaries['assetName-filter'].countReturned !== 1 || !searchSummaries['assetName-filter'].paths[0]?.includes('BP_Dropped_Magazine')) {
    throw new Error('Asset-name filter did not resolve the known indexed Blueprint-like package.');
  }
  if (inspectionSummaries['index-only-blueprint'].status !== 'indexed') {
    throw new Error('Index-only inspection must return status=indexed.');
  }
  const loadSummary = decode(loadResult);
  if (loadSummary.indexedFileCount !== 34238 || loadSummary.indexedPackageCount !== 23983) {
    throw new Error(`Unexpected file/package counts: ${JSON.stringify({ files: loadSummary.indexedFileCount, packages: loadSummary.indexedPackageCount })}`);
  }
  const mappingValidation = decode(mappingValidationResult);
  if (!validateMappingsTool || mappingValidation?.status !== 'blocked_no_mapping_path') {
    throw new Error(`validate_mappings did not expose the explicit no-mapping block: ${JSON.stringify(mappingValidation)}`);
  }
  const subsystemDiscovery = decode(subsystemDiscoveryResult);
  if (!discoverSubsystemsTool || subsystemDiscovery?.status !== 'candidate_paths_only' || subsystemDiscovery?.indexedPackageCount !== 23983 || subsystemDiscovery?.groups?.length !== 6 || subsystemDiscovery?.persistentIndexAvailable !== true) {
    throw new Error(`Unexpected subsystem discovery result: ${JSON.stringify(subsystemDiscovery)}`);
  }
  if (subsystemDiscovery.groups.some(group => group.countReturned !== 5 || !group.hasMore || group.nextOffset !== 5)) {
    throw new Error('Subsystem groups did not return the expected bounded first page and nextOffset.');
  }
  const catalogValidation = decode(catalogValidationResult);
  if (!validateCatalogTool || catalogValidation?.packagePathComparison?.equivalent !== true || catalogValidation?.searchQueryComparison?.equivalent !== true || catalogValidation?.subsystemQueryComparison?.equivalent !== true || catalogValidation?.catalog?.packageCount !== 23983 || catalogValidation?.catalog?.integrityCheck !== 'ok') {
    throw new Error(`SQLite catalog did not match the mounted in-memory package index: ${JSON.stringify(catalogValidation)}`);
  }
  if (catalogValidation.catalog.analysisHistoryCount < 5) {
    throw new Error(`Expected bounded inspection attempts to be persisted in analysis history: ${JSON.stringify(catalogValidation.catalog)}`);
  }
  for (const sample of Object.keys(inspectionSummaries).filter(key => key.endsWith('.uasset'))) {
    if (inspectionSummaries[sample].status !== 'failed' || inspectionSummaries[sample].exceptionType !== 'CUE4Parse.UE4.Exceptions.MappingException') {
      throw new Error(`Unexpected parse result for ${sample}: ${JSON.stringify(inspectionSummaries[sample])}`);
    }
  }
  console.log(JSON.stringify({
    tools: names,
    profile: decode(profileResult),
    load: loadSummary,
    searches: searchSummaries,
    inspections: inspectionSummaries,
    mappingValidation,
    catalogValidation,
    subsystemDiscovery: {
      status: subsystemDiscovery.status,
      indexSource: subsystemDiscovery.indexSource,
      persistentIndexAvailable: subsystemDiscovery.persistentIndexAvailable,
      indexedPackageCount: subsystemDiscovery.indexedPackageCount,
      groups: subsystemDiscovery.groups.map(group => ({
        subsystemId: group.subsystemId,
        queryTerms: group.queryTerms,
        totalCandidatePackages: group.totalCandidatePackages,
        countReturned: group.countReturned,
        hasMore: group.hasMore,
        nextOffset: group.nextOffset,
        candidatePaths: group.candidates.map(item => item.path)
      }))
    },
    containerLogEventCount: decode(diagnosticResult)?.cue4parseLogEventCount
  }, null, 2));
} finally {
  child.kill();
}




