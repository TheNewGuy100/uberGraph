import java.io.*;
import java.nio.charset.StandardCharsets;
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.address.AddressSet;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.Reference;
import ghidra.app.decompiler.*;

// No whole-image analysis. Entries must come from independently recorded PE evidence.
public class TargetedNativeFunctions extends GhidraScript {
    public void run() throws Exception {
        String[] args = getScriptArgs();
        if (args.length < 2) throw new IllegalArgumentException("output path and entry addresses required");
        try (PrintWriter out = new PrintWriter(new OutputStreamWriter(new FileOutputStream(args[0]), StandardCharsets.UTF_8))) {
            DecompInterface d = new DecompInterface();
            try {
                d.openProgram(currentProgram);
                for (int i = 1; i < args.length; i++) {
                    String[] bounds = args[i].split(":");
                    Address entry = toAddr(Long.decode(bounds[0]));
                    out.println("ENTRY " + entry);
                    out.println("DISASSEMBLE " + disassemble(entry));
                    Function fn = getFunctionAt(entry);
                    if (fn == null) fn = createFunction(entry, null);
                    if (fn == null) { out.println("NO_FUNCTION"); continue; }
                    if (bounds.length == 2) {
                        Address end = toAddr(Long.decode(bounds[1])).subtract(1);
                        // Selected unwind chunks can belong to the same function. Earlier targeted
                        // passes may have created standalone chunk functions in this analysis DB.
                        FunctionIterator overlaps = currentProgram.getFunctionManager().getFunctions(entry, true);
                        java.util.ArrayList<Address> chunks = new java.util.ArrayList<>();
                        while (overlaps.hasNext()) {
                            Function other = overlaps.next();
                            if (other.getEntryPoint().compareTo(end) > 0) break;
                            if (!other.getEntryPoint().equals(entry)) chunks.add(other.getEntryPoint());
                        }
                        for (Address chunk : chunks) removeFunction(getFunctionAt(chunk));
                        fn.setBody(new AddressSet(entry, end));
                    }
                    out.println("BODY " + fn.getBody());
                    InstructionIterator it = currentProgram.getListing().getInstructions(fn.getBody(), true);
                    int count = 0;
                    while (it.hasNext() && count++ < 2000) {
                        Instruction ins = it.next();
                        out.print("INS " + ins.getAddress() + " " + ins);
                        for (Reference ref : ins.getReferencesFrom()) out.print(" REF " + ref.getReferenceType() + "->" + ref.getToAddress());
                        out.println();
                    }
                    DecompileResults r = d.decompileFunction(fn, 30, monitor);
                    out.println("DECOMPILED " + r.decompileCompleted() + " " + r.getErrorMessage());
                    if (r.getDecompiledFunction() != null) out.println(r.getDecompiledFunction().getC());
                    out.flush();
                }
            } finally { d.dispose(); }
        }
    }
}
