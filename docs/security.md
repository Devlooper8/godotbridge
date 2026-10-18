# Security model

The bridge controls a trusted local Godot project. Authentication restricts who
can request edits; it is not a sandbox for malicious project scripts or for a
compromised process running as the same OS user.

- Only `127.0.0.1` is bound. There is no remote/network-wide mode or configurable
  remote host. Python rejects non-loopback endpoints in connection files.
- A cryptographically random 256-bit session token is compared in constant time.
  Tokens rotate when the plugin restarts and are omitted from normal logs/results.
- The private credential directory is restricted before token creation: 0700
  directory and 0600 file on Unix; inherited ACLs removed and current-user full
  control granted on Windows. Broad built-in grants are removed. Native `whoami`
  and `icacls` are called once at startup with fixed argument arrays, without a shell.
  Startup fails if permissions cannot be restricted. No request can invoke them.
- Frame size, clients, outstanding requests, idle time, schema depth, node count,
  image dimensions and returned log size are bounded. Polling never blocks on
  incomplete network input.
- Both client and plugin validate arguments. Node/resource creation uses explicit
  allowlists. Properties cannot reach scripts, owners, arbitrary objects or methods; the only
  non-allowlisted properties are a node's exported script variables, type-checked.
- Node paths cannot escape the edited root. Scene paths are `res://` `.tscn`
  paths and reject traversal, private directories and symbolic links. Python
  resolves output/resource paths and confines them to the configured project.
  Private worker storage also checks resolved paths.
- Scene creation/save-as and image writes refuse existing destinations. Scene
  saves compare fingerprints to detect external changes. Use Git for recovery;
  scene creation/saving are not undoable filesystem operations.
- The editor owns live mutations. Headless import is refused while the bridge
  editor is connected. Do not run a separate non-bridge editor on the same project
  during offline imports: its presence cannot reliably be detected by this release.
- The CLI never kills a PID loaded from disk. A supervisor stops only the Popen
  child it launched. Process commands use argument arrays and `shell=False`.
- MCP is stdio-only. No arbitrary GDScript, generic method invocation, shell
  execution, or unrestricted filesystem tool is exposed.

## Practical boundaries

Godot itself executes project code during editor loading, tool-script activity,
scene `_init` smoke tests and runtime play. Validation and game execution are
for trusted projects. Geometry previews avoid instantiating scene scripts, but
render existing assets/shaders in the trusted editor process.

Inherited-scene nodes can be overridden but not deleted, renamed, reparented or
duplicated. Scene instances follow the editor: only the instance root is editable unless editable children is enabled.
Nodes with non-`@tool` scripts are editable (the editor only runs placeholder
instances for them); `@tool` script nodes require the explicit `allow_tool_script`
opt-in. This policy avoids ambiguous ownership. It can be relaxed only with explicit engine tests for each new behavior.

Project-local scripts running with the same user's rights can already access the
token and project. Shared/network folders and pre-existing unusual explicit ACLs
need normal OS access review. Filesystem checks are not hardened against a
malicious same-user process racing symlink replacements or saves.

Timed-out requests may already have mutated the scene. The client intentionally
does not replay them. Inspect state and undo if needed. Authentication is not an
approval prompt: an authenticated agent can delete owned nodes and save scenes.

Keep `.godot/`, `.godotbridge/`, logs and generated captures out of source control.
An abandoned capture stays in the private cache; clean it while the editor is
closed. Managed games have a default one-hour lifetime to limit orphaned runs.
