import argparse
import hashlib
import json
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
sys.path[:0] = [str(ROOT / 'core/aot'), str(ROOT / '3rdparty/pyelftools'), str(ROOT / '3rdparty/capstone/bindings/python')]


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--app', type=Path, required=True)
    parser.add_argument('--module', type=Path, required=True)
    parser.add_argument('--build-root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    build, output = args.build_root.resolve(), args.output.resolve()
    require(1 <= args.jobs <= 8, 'jobs must be between one and eight')
    require(not output.exists(), 'choose a fresh output directory')
    manifest = json.loads((HERE / 'bindings.json').read_text())
    for name, expected in manifest['sources'].items():
        require(digest(ROOT / name) == expected, f'provider source changed; review its contract: {name}')
    app, module = args.app.resolve(), args.module.resolve()
    require(digest(app) == manifest['inputs']['app'], 'application input changed')
    require(digest(module) == manifest['inputs']['module'], 'module input changed')
    cache = (build / 'CMakeCache.txt').read_text()
    require(f'CMAKE_HOME_DIRECTORY:INTERNAL={ROOT}\n' in cache, 'native build belongs to a different checkout')
    require('ANYPS5_NATIVE_GRAPHICS:BOOL=ON' in cache, 'native graphics build required')
    subprocess.run(['cmake', '--build', str(build), '--target', 'anyps5_native_services', 'capstone_shared', '-j', str(args.jobs)], check=True)
    os.environ['LIBCAPSTONE_PATH'] = str(build / 'core/aot/capstone')
    import guest_emit
    import guest_lift
    output.mkdir(parents=True)
    programs, reports = {}, {}
    imports = set()
    for name, path, abi in [('app', app, 'sce-app'), ('shim', module, 'sce-module')]:
        program = guest_lift.Program(path.read_bytes(), abi=abi)
        programs[name] = program
        for symbol in program.dynamic['symbols']:
            if not symbol['section'] and symbol['name']:
                imports.add(guest_emit.canonical_name(program, symbol))
        report = guest_emit.build(path, output / (name + '-ir'), shards=32 if name == 'app' else 1,
                                  jobs=args.jobs, abi=abi, namespace=name + '_', concurrent=True, ordered_access='atomic')
        require(not report['unsupported'], 'unqualified instruction sites remain')
        reports[name] = report
    require(imports == set(manifest['bindings']), 'import identities changed')
    def compile_ir(path):
        subprocess.run(['xcrun', 'clang', '-O2', '-arch', 'arm64', '-Wno-override-module', '-c', str(path), '-o', str(path.with_suffix('.o'))], check=True)
    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        list(pool.map(compile_ir, sorted(output.glob('*-ir/*.ll'))))
    names = sorted({r['native'] for r in manifest['bindings'].values() if 'native' in r})
    rows, extras, prototypes = [], [], set()
    for identity, record in manifest['bindings'].items():
        if 'bridge' in record:
            extras.append('{' + json.dumps(identity) + ', NativeAotSce::CrtProvider(' + json.dumps(record['name']) + '), nullptr, false, false, nullptr}')
        elif 'prototype' in record:
            name = record['native']
            prototypes.add(record['prototype'] + ';')
            provider = 'ReplayDebugOutText' if name == 'sceKernelDebugOutText' else name
            extras.append('{' + json.dumps(identity) + ', NativeAotSce::ScalarBridge<' + provider + '>, nullptr, false, false, reinterpret_cast<const void*>(' + name + ')}')
        else:
            name = record['native']
            rows.append('{' + json.dumps(identity) + ',' + json.dumps(name) + ',OriginalNativeBindings[' + str(names.index(name)) + '],' + str(record['data']).lower() + '},')
    source = (HERE.parent / 'original_sce/driver.cpp.in').read_text()
    source = 'int ReplayDebugOutText(int, const char*);\n' + source
    source += (HERE / 'replay.cpp.in').read_text().replace('GAMETIC_ADDRESS', str(manifest['gametic_address']))
    process = next(s for s in programs['app'].view.segments if s['type'] == 0x61000001)
    tags = programs['shim'].dynamic['tags']
    require(tags.get('DT_INIT_ARRAYSZ', 0) == tags.get('DT_FINI_ARRAYSZ', 0) == 0, 'module initializer arrays changed')
    for key, value in [('INIT_ADDRESS', tags['DT_INIT']), ('FINI_ADDRESS', tags['DT_FINI']),
                       ('PROCESS_ADDRESS', process['vaddr']), ('PROCESS_BYTES', process['memsz'])]:
        source = source.replace(key, str(value))
    source = source.replace('ROWS', '\n'.join(rows))
    source = source.replace('    NativeAotSce::Register(bindings);',
                            '    NativeAotSce::Register(bindings);\n    const NativeAotGuest::ProviderBinding extra[] = {\n' + ',\n'.join(extras) + '\n};\n    NativeAotGuest::RegisterProviders(extra, std::size(extra));')
    headers = ['native/NativeAotSceAbi.hpp', 'native/NativeAotSceCrt.hpp', 'SceTypes.hpp', 'prx/libc/include/FileStream.hpp',
               'prx/libc/include/GuestTime.hpp', 'prx/libkernel/Socket/include/GuestPoll.hpp', 'prx/libSceAgc/Cb/include/Dispatch.hpp']
    source = ''.join('#include "' + header + '"\n' for header in headers) + 'extern "C" {\n' + '\n'.join(sorted(prototypes)) + '\n}\n' + source
    (output / 'driver.cpp').write_text(source)
    (output / 'bindings.S').write_text('.section __DATA_CONST,__const\n.p2align 3\n.globl _OriginalNativeBindings\n_OriginalNativeBindings:\n' + ''.join('.quad _' + name + '\n' for name in names))
    command = ['xcrun', 'clang++', '-std=c++20', '-O2', '-arch', 'arm64', '-fexperimental-library', '-I' + str(ROOT / 'core/libs')]
    objects = []
    for path in [output / 'driver.cpp', output / 'bindings.S', ROOT / 'core/libs/native/NativeAotGuest.cpp',
                 ROOT / 'core/libs/native/NativeAotSce.cpp', ROOT / 'core/libs/native/NativeAotSceCrt.cpp']:
        obj = output / (path.stem + '.o')
        subprocess.run(command + ['-c', str(path), '-o', str(obj)], check=True)
        objects.append(obj)
    objects += sorted(output.glob('*-ir/*.o'))
    libraries = ['core/libs/native/libanyps5_native_services.a', 'core/libs/native/libanyps5_native_graphics.a',
                 'libjpeg-turbo/lib/libturbojpeg.a', '3rdparty/SDL2/libSDL2.a', 'core/libs/native/libshader_recompiler_native.a',
                 '3rdparty/glslang/SPIRV/libSPIRV.a', '3rdparty/glslang/glslang/libglslang.a',
                 'core/libs/native/libdecoder_png_native.a', 'core/aot/libanyps5_native_image.a',
                 '3rdparty/mbedtls/library/libmbedx509.a', '3rdparty/mbedtls/library/libmbedcrypto.a', '3rdparty/mbedtls/3rdparty/p256-m/libp256m.a',
                 'libzarchive.a', '3rdparty/zstd/lib/libzstd.a']
    frameworks = ['CoreVideo', 'Cocoa', 'IOKit', 'ForceFeedback', 'Carbon', 'CoreAudio', 'AudioToolbox', 'AVFoundation',
                  'Foundation', 'GameController', 'Metal', 'QuartzCore', 'CoreHaptics', 'CoreFoundation']
    link = ['-Wl,-dead_strip'] + [str(path) for path in objects] + [str(build / path) for path in libraries]
    for framework in frameworks:
        link += ['-framework', framework]
    subprocess.run(command + link + ['-o', str(output / 'doom')], check=True)
    receipt = {'manifest_sha256': digest(HERE / 'bindings.json'), 'inputs': manifest['inputs'], 'reports': reports,
               'consumer_sources': {str(p.relative_to(ROOT)): digest(p) for p in [Path(__file__), HERE / 'replay.cpp.in', HERE.parent / 'original_sce/driver.cpp.in']},
               'compiler_sources': {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / 'core/aot').glob('*.py'))},
               'runtime_sources': manifest['sources'], 'libraries': {path: digest(build / path) for path in libraries},
               'binary_sha256': digest(output / 'doom'), 'runtime_verified': False}
    (output / 'receipt.json').write_text(json.dumps(receipt, indent=2) + '\n')


if __name__ == '__main__':
    main()
