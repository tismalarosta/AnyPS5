if(NOT APPLE AND NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    message(FATAL_ERROR "The native AOT compiler supports Apple ARM64 execution or Linux cross-compilation")
endif()
if(APPLE AND NOT CMAKE_SYSTEM_PROCESSOR MATCHES "arm64|aarch64")
    message(FATAL_ERROR "Native AOT execution tests require an Apple ARM64 host")
endif()
if(CMAKE_OSX_ARCHITECTURES AND NOT CMAKE_OSX_ARCHITECTURES STREQUAL "arm64")
    message(FATAL_ERROR "The experimental native AOT tool requires an arm64 build")
endif()

set(aotNativeExecution OFF)
if(APPLE OR CMAKE_SYSTEM_PROCESSOR MATCHES "^(arm64|aarch64)$")
    set(aotNativeExecution ON)
endif()
find_package(Python3 REQUIRED COMPONENTS Interpreter)
if(NOT APPLE)
    set(aotClang clang CACHE STRING "Clang executable for Apple ARM64 cross-compilation")
    execute_process(COMMAND ${aotClang} --version RESULT_VARIABLE aotClangStatus OUTPUT_QUIET ERROR_QUIET)
    if(NOT aotClangStatus EQUAL 0)
        message(FATAL_ERROR "Set aotClang to a Clang executable with the AArch64 backend")
    endif()
    set(aotClangEnvironment "ANYPS5_AOT_CLANG=${aotClang}")
endif()
enable_language(C)
set(BUILD_SHARED_LIBS ON)
set(BUILD_STATIC_LIBS OFF)
set(CAPSTONE_ARCHITECTURE_DEFAULT OFF)
set(CAPSTONE_X86_SUPPORT ON)
set(CAPSTONE_BUILD_MACOS_THIN ON)
set(CAPSTONE_BUILD_TESTS OFF)
set(CAPSTONE_BUILD_CSTOOL OFF)
set(CAPSTONE_BUILD_CSTEST OFF)
add_subdirectory(${CMAKE_SOURCE_DIR}/3rdparty/capstone ${CMAKE_CURRENT_BINARY_DIR}/capstone EXCLUDE_FROM_ALL)

set(aotPythonPath "${CMAKE_SOURCE_DIR}/3rdparty/capstone/bindings/python:${CMAKE_SOURCE_DIR}/3rdparty/pyelftools:${CMAKE_CURRENT_SOURCE_DIR}")
configure_file(launcher.py.in native_aot.py @ONLY)
add_custom_target(native_aot ALL DEPENDS capstone_shared)
add_library(anyps5_native_image STATIC "${CMAKE_SOURCE_DIR}/core/libs/native/NativeAotImage.cpp"
    "${CMAKE_SOURCE_DIR}/core/libs/native/NativeAotPointer.cpp"
    "${CMAKE_SOURCE_DIR}/core/libs/native/NativeAotBundle.cpp"
    "${CMAKE_SOURCE_DIR}/core/libs/prx/libkernel/Pthread/src/GuestTlsMacOs.cpp")
target_compile_definitions(anyps5_native_image PRIVATE APS5_NATIVE_TLS_POSIX=1)
find_package(Threads REQUIRED)
target_link_libraries(anyps5_native_image PUBLIC Threads::Threads)
if(APPLE)
    target_sources(anyps5_native_image PRIVATE "${CMAKE_SOURCE_DIR}/core/libs/native/NativeAotReadonly.cpp")
else()
    target_sources(anyps5_native_image PRIVATE "${CMAKE_SOURCE_DIR}/core/libs/native/NativeAotReadonlyLinux.cpp")
endif()
target_include_directories(anyps5_native_image PUBLIC "${CMAKE_SOURCE_DIR}/core/libs")
set_target_properties(anyps5_native_image PROPERTIES CXX_EXTENSIONS OFF)

if(BUILD_TESTING)
    add_test_executable(native_aot_thread_boundary_tests "${CMAKE_SOURCE_DIR}/core/libs/tests/NativeAotThreads.cpp"
        "${CMAKE_SOURCE_DIR}/core/libs/native/NativeAotThreads.cpp")
    target_link_libraries(native_aot_thread_boundary_tests PRIVATE anyps5_native_image)
    add_test(NAME native_aot_thread_boundary COMMAND native_aot_thread_boundary_tests)
    set_tests_properties(native_aot_thread_boundary PROPERTIES TIMEOUT 30)
    add_test_executable(native_aot_bundle_tests "${CMAKE_SOURCE_DIR}/core/libs/tests/NativeAotBundle.cpp")
    target_link_libraries(native_aot_bundle_tests PRIVATE anyps5_native_image)
    add_test(NAME native_aot_bundle COMMAND native_aot_bundle_tests)
    set_tests_properties(native_aot_bundle PROPERTIES TIMEOUT 30)
    add_test_executable(native_aot_graphics_layout_tests "${CMAKE_SOURCE_DIR}/core/libs/tests/NativeAotGraphicsLayouts.cpp")
    target_include_directories(native_aot_graphics_layout_tests PRIVATE "${CMAKE_SOURCE_DIR}/core/libs")
    add_test(NAME native_aot_graphics_layouts COMMAND native_aot_graphics_layout_tests)
    set_tests_properties(native_aot_graphics_layouts PROPERTIES TIMEOUT 30)
    add_test_executable(native_aot_readonly_tests "${CMAKE_SOURCE_DIR}/core/libs/tests/NativeAotReadonly.cpp")
    target_link_libraries(native_aot_readonly_tests PRIVATE anyps5_native_image)
    add_test(NAME native_aot_readonly COMMAND native_aot_readonly_tests)
    set_tests_properties(native_aot_readonly PROPERTIES TIMEOUT 30)
    add_test_executable(native_aot_image_tests "${CMAKE_SOURCE_DIR}/core/libs/tests/NativeAotImage.cpp")
    target_link_libraries(native_aot_image_tests PRIVATE anyps5_native_image)
    add_test(NAME native_aot_image COMMAND native_aot_image_tests)
    set_tests_properties(native_aot_image PROPERTIES TIMEOUT 30)
    set(aotTestCommand ${CMAKE_COMMAND} -E env ${aotClangEnvironment}
        "LIBCAPSTONE_PATH=$<TARGET_FILE_DIR:capstone_shared>" "PYTHONPATH=${aotPythonPath}" ${Python3_EXECUTABLE})
    function(aot_test_cases testSource)
        get_filename_component(suite "${testSource}" NAME_WE)
        string(REGEX REPLACE "^test_" "" suite "${suite}")
        set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS "${testSource}")
        execute_process(COMMAND ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/tests/list_cases.py" "${testSource}"
            OUTPUT_VARIABLE cases OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
        string(REPLACE "\n" ";" cases "${cases}")
        if(NOT cases)
            message(FATAL_ERROR "${testSource} has no test cases")
        endif()
        list(POP_FRONT cases first)
        foreach(case IN LISTS cases)
            add_test(NAME native_aot_${suite}.${case} COMMAND ${aotTestCommand} "${testSource}" "${case}")
            set_tests_properties(native_aot_${suite}.${case} PROPERTIES TIMEOUT 30)
        endforeach()
        set(aotFirstCase "${first}" PARENT_SCOPE)
    endfunction()
    aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_portable.py")
    add_test(NAME native_aot_portable.${aotFirstCase} COMMAND ${aotTestCommand}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_portable.py" "${aotFirstCase}")
    set_tests_properties(native_aot_portable.${aotFirstCase} PROPERTIES TIMEOUT 30)
    aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_contract_recipe.py")
    add_test(NAME native_aot_contract_recipe.${aotFirstCase} COMMAND ${aotTestCommand}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_contract_recipe.py" "${aotFirstCase}")
    set_tests_properties(native_aot_contract_recipe.${aotFirstCase} PROPERTIES TIMEOUT 30)
    aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_provider_catalog.py")
    add_test(NAME native_aot_provider_catalog.${aotFirstCase} COMMAND ${aotTestCommand}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_provider_catalog.py" "${aotFirstCase}")
    set_tests_properties(native_aot_provider_catalog.${aotFirstCase} PROPERTIES TIMEOUT 30)
    aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_debug_candidates.py")
    add_test(NAME native_aot_debug_candidates.${aotFirstCase} COMMAND ${aotTestCommand}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_debug_candidates.py" "${aotFirstCase}")
    set_tests_properties(native_aot_debug_candidates.${aotFirstCase} PROPERTIES TIMEOUT 30)
    aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_load_facts.py")
    add_test(NAME native_aot_load_facts.${aotFirstCase} COMMAND ${aotTestCommand}
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_load_facts.py" "${aotFirstCase}")
    set_tests_properties(native_aot_load_facts.${aotFirstCase} PROPERTIES TIMEOUT 30)
    if(APPLE)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_abi.py")
        add_test(NAME native_aot_abi.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_abi.py" "${aotFirstCase}")
        set_tests_properties(native_aot_abi.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_avx.py")
        add_test(NAME native_aot_avx.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_avx.py" "${aotFirstCase}")
        set_tests_properties(native_aot_avx.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_bundle.py")
        add_test(NAME native_aot_bundle.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_bundle.py" "${aotFirstCase}")
        set_tests_properties(native_aot_bundle.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_calls.py")
        add_test(NAME native_aot_calls.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_calls.py" "${aotFirstCase}")
        set_tests_properties(native_aot_calls.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_checked_pointers.py")
        add_test(NAME native_aot_checked_pointers.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_checked_pointers.py" "${aotFirstCase}")
        set_tests_properties(native_aot_checked_pointers.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_checked_stack.py")
        add_test(NAME native_aot_checked_stack.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_checked_stack.py" "${aotFirstCase}")
        set_tests_properties(native_aot_checked_stack.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_compiler.py")
        add_test(NAME native_aot_compiler.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_compiler.py" "${aotFirstCase}")
        set_tests_properties(native_aot_compiler.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_contract_recipe_execution.py")
        add_test(NAME native_aot_contract_recipe_execution.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_contract_recipe_execution.py" "${aotFirstCase}")
        set_tests_properties(native_aot_contract_recipe_execution.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_debug_pointer_loads.py")
        add_test(NAME native_aot_debug_pointer_loads.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_debug_pointer_loads.py" "${aotFirstCase}")
        set_tests_properties(native_aot_debug_pointer_loads.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_doom_replay.py")
        add_test(NAME native_aot_doom_replay.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_doom_replay.py" "${aotFirstCase}")
        set_tests_properties(native_aot_doom_replay.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_dynamic.py")
        add_test(NAME native_aot_dynamic.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_dynamic.py" "${aotFirstCase}")
        set_tests_properties(native_aot_dynamic.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_effects.py")
        add_test(NAME native_aot_effects.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_effects.py" "${aotFirstCase}")
        set_tests_properties(native_aot_effects.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_finite_tables.py")
        add_test(NAME native_aot_finite_tables.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_finite_tables.py" "${aotFirstCase}")
        set_tests_properties(native_aot_finite_tables.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_graphics_invariants.py")
        add_test(NAME native_aot_graphics_invariants.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_graphics_invariants.py" "${aotFirstCase}")
        set_tests_properties(native_aot_graphics_invariants.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_avx.py")
        add_test(NAME native_aot_guest_avx.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_avx.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_avx.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_bit_test.py")
        add_test(NAME native_aot_guest_bit_test.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_bit_test.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_bit_test.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_bulk.py")
        add_test(NAME native_aot_guest_bulk.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_bulk.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_bulk.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_bundle.py")
        add_test(NAME native_aot_guest_bundle.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_bundle.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_bundle.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_call_boundaries.py")
        add_test(NAME native_aot_guest_call_boundaries.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_call_boundaries.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_call_boundaries.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_call_effects.py")
        add_test(NAME native_aot_guest_call_effects.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_call_effects.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_call_effects.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_epoch_calls.py")
        add_test(NAME native_aot_guest_epoch_calls.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_epoch_calls.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_epoch_calls.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_extract_endian.py")
        add_test(NAME native_aot_guest_extract_endian.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_extract_endian.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_extract_endian.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_lowering.py")
        add_test(NAME native_aot_guest_lowering.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_lowering.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_lowering.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_profiles.py")
        add_test(NAME native_aot_guest_profiles.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_profiles.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_profiles.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_value_leaves.py")
        add_test(NAME native_aot_guest_value_leaves.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_value_leaves.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_value_leaves.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_float.py")
        add_test(NAME native_aot_guest_vex_float.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_float.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_vex_float.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_integer.py")
        add_test(NAME native_aot_guest_vex_integer.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_integer.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_vex_integer.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_mask_fma.py")
        add_test(NAME native_aot_guest_vex_mask_fma.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_mask_fma.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_vex_mask_fma.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_moves.py")
        add_test(NAME native_aot_guest_vex_moves.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_moves.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_vex_moves.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_permute.py")
        add_test(NAME native_aot_guest_vex_permute.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_permute.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_vex_permute.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_residual.py")
        add_test(NAME native_aot_guest_vex_residual.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_guest_vex_residual.py" "${aotFirstCase}")
        set_tests_properties(native_aot_guest_vex_residual.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_immutable_data.py")
        add_test(NAME native_aot_immutable_data.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_immutable_data.py" "${aotFirstCase}")
        set_tests_properties(native_aot_immutable_data.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_integer.py")
        add_test(NAME native_aot_integer.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_integer.py" "${aotFirstCase}")
        set_tests_properties(native_aot_integer.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_loop_ranges.py")
        add_test(NAME native_aot_loop_ranges.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_loop_ranges.py" "${aotFirstCase}")
        set_tests_properties(native_aot_loop_ranges.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_memory_writes.py")
        add_test(NAME native_aot_memory_writes.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_memory_writes.py" "${aotFirstCase}")
        set_tests_properties(native_aot_memory_writes.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_module_lifecycle.py")
        add_test(NAME native_aot_module_lifecycle.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_module_lifecycle.py" "${aotFirstCase}")
        set_tests_properties(native_aot_module_lifecycle.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_module_tls.py")
        add_test(NAME native_aot_module_tls.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_module_tls.py" "${aotFirstCase}")
        set_tests_properties(native_aot_module_tls.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_native_image.py")
        add_test(NAME native_aot_native_image.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_native_image.py" "${aotFirstCase}")
        set_tests_properties(native_aot_native_image.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_parameter_effects.py")
        add_test(NAME native_aot_parameter_effects.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_parameter_effects.py" "${aotFirstCase}")
        set_tests_properties(native_aot_parameter_effects.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pointer_outputs.py")
        add_test(NAME native_aot_pointer_outputs.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pointer_outputs.py" "${aotFirstCase}")
        set_tests_properties(native_aot_pointer_outputs.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pointer_provenance.py")
        add_test(NAME native_aot_pointer_provenance.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_pointer_provenance.py" "${aotFirstCase}")
        set_tests_properties(native_aot_pointer_provenance.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_provider_effects.py")
        add_test(NAME native_aot_provider_effects.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_provider_effects.py" "${aotFirstCase}")
        set_tests_properties(native_aot_provider_effects.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_recover.py")
        add_test(NAME native_aot_recover.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_recover.py" "${aotFirstCase}")
        set_tests_properties(native_aot_recover.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_regressions.py")
        add_test(NAME native_aot_regressions.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_regressions.py" "${aotFirstCase}")
        set_tests_properties(native_aot_regressions.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stack_origins.py")
        add_test(NAME native_aot_stack_origins.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stack_origins.py" "${aotFirstCase}")
        set_tests_properties(native_aot_stack_origins.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stack_values.py")
        add_test(NAME native_aot_stack_values.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_stack_values.py" "${aotFirstCase}")
        set_tests_properties(native_aot_stack_values.${aotFirstCase} PROPERTIES TIMEOUT 30)
        aot_test_cases("${CMAKE_CURRENT_SOURCE_DIR}/tests/test_vectors.py")
        add_test(NAME native_aot_vectors.${aotFirstCase} COMMAND ${aotTestCommand}
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/test_vectors.py" "${aotFirstCase}")
        set_tests_properties(native_aot_vectors.${aotFirstCase} PROPERTIES TIMEOUT 30)
    endif()
endif()

option(ANYPS5_NATIVE_AOT_EXAMPLE "Build the source-based native runtime example" OFF)
if(ANYPS5_NATIVE_AOT_EXAMPLE)
    set(ps5linkSource "${CMAKE_SOURCE_DIR}/3rdparty/ps5link-sdk/linker")
    if(NOT EXISTS "${ps5linkSource}/link_real.c")
        message(FATAL_ERROR "Initialize the pinned 3rdparty/ps5link-sdk source submodule")
    endif()
    add_executable(aot_ps5link
        ${ps5linkSource}/link_real.c ${ps5linkSource}/elf_object.c
        ${ps5linkSource}/linker.c ${ps5linkSource}/dynwriter.c
        ${ps5linkSource}/catalog.c ${ps5linkSource}/catalog_extra.c
        ${ps5linkSource}/catalog_lookup.c ${ps5linkSource}/nid.c ${ps5linkSource}/sha1.c)
    add_library(anyps5_native_runtime STATIC
        ../libs/prx/libc/src/LocaleSupport.cpp
        ../libs/prx/libc/src/ApplicationHeap.cpp
        ../libs/prx/libc/src/GuestHeap.cpp
        ../libs/prx/libc/src/GuestArena.cpp
        ../libs/prx/libc/src/GuestAllocations.cpp
        ../libs/prx/libkernel/Time/TimedWait.cpp
        ../libs/prx/libkernel/System/src/Notification.cpp
        ../libs/native/NativeAotTime.cpp)
    target_include_directories(anyps5_native_runtime PUBLIC "${CMAKE_SOURCE_DIR}/core/libs")
    target_compile_options(anyps5_native_runtime PRIVATE -ffunction-sections -fdata-sections)
    target_link_libraries(anyps5_native_runtime PUBLIC anyps5_native_image)
    if(aotNativeExecution)
        target_sources(anyps5_native_runtime PRIVATE ../libs/native/NativeAotMain.cpp)
    endif()
    if(BUILD_TESTING)
        add_test_executable(native_aot_runtime_tests "${CMAKE_SOURCE_DIR}/core/libs/tests/NativeAotRuntime.cpp")
        target_link_libraries(native_aot_runtime_tests PRIVATE anyps5_native_runtime)
        if(APPLE)
            target_link_options(native_aot_runtime_tests PRIVATE -Wl,-dead_strip)
        else()
            target_link_options(native_aot_runtime_tests PRIVATE -Wl,--gc-sections)
        endif()
        add_test(NAME native_aot_runtime COMMAND native_aot_runtime_tests)
        set_tests_properties(native_aot_runtime PROPERTIES TIMEOUT 30)
    endif()
    set(aotExampleCommand ${CMAKE_COMMAND} -E env ${aotClangEnvironment}
        "LIBCAPSTONE_PATH=$<TARGET_FILE_DIR:capstone_shared>"
        "PYTHONPATH=${aotPythonPath}"
        ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/examples/hello_notify.py"
        --sdk "${CMAKE_SOURCE_DIR}/3rdparty/ps5link-sdk"
        --linker $<TARGET_FILE:aot_ps5link>
        --output "${CMAKE_CURRENT_BINARY_DIR}/hello-notify")
    if(aotNativeExecution)
        list(APPEND aotExampleCommand --runtime $<TARGET_FILE:anyps5_native_runtime>
            --image-runtime $<TARGET_FILE:anyps5_native_image>)
        if(NOT APPLE)
            list(APPEND aotExampleCommand --target linux-arm64)
        endif()
        add_custom_target(native_aot_hello_notify
            COMMAND ${aotExampleCommand} --run
            DEPENDS aot_ps5link anyps5_native_runtime capstone_shared
            USES_TERMINAL)
        add_custom_target(native_aot_hello_notify_original
            COMMAND ${aotExampleCommand} --original-delay --run
            DEPENDS aot_ps5link anyps5_native_runtime capstone_shared
            USES_TERMINAL)
        if(BUILD_TESTING)
            add_test(NAME native_aot_hello_notify COMMAND ${aotExampleCommand} --run)
            set_tests_properties(native_aot_hello_notify PROPERTIES TIMEOUT 30)
        endif()
    else()
        add_custom_target(native_aot_hello_notify
            COMMAND ${aotExampleCommand} --compile-only
            DEPENDS aot_ps5link capstone_shared USES_TERMINAL)
        if(BUILD_TESTING)
            add_test(NAME native_aot_hello_notify_compile COMMAND ${aotExampleCommand} --compile-only)
            set_tests_properties(native_aot_hello_notify_compile PROPERTIES TIMEOUT 30)
        endif()
    endif()
    if(APPLE)
        set(padCompileCommand ${CMAKE_COMMAND} -E env "LIBCAPSTONE_PATH=$<TARGET_FILE_DIR:capstone_shared>"
            "PYTHONPATH=${aotPythonPath}" ${Python3_EXECUTABLE} "${CMAKE_CURRENT_SOURCE_DIR}/examples/pad_input/build.py"
            --sdk "${CMAKE_SOURCE_DIR}/3rdparty/ps5link-sdk" --linker $<TARGET_FILE:aot_ps5link>
            --output-parent "${CMAKE_CURRENT_BINARY_DIR}/pad-compile-runs")
        add_custom_target(native_aot_pad_input_compile COMMAND ${padCompileCommand}
            DEPENDS aot_ps5link capstone_shared USES_TERMINAL)
        if(BUILD_TESTING)
            add_test(NAME native_aot_pad_input_compile COMMAND ${padCompileCommand})
            add_test(NAME native_aot_pad_input_optimized_compile COMMAND ${padCompileCommand} --optimization O2)
            set_tests_properties(native_aot_pad_input_optimized_compile PROPERTIES TIMEOUT 30)
            set_tests_properties(native_aot_pad_input_compile PROPERTIES TIMEOUT 30)
        endif()
    endif()
endif()
