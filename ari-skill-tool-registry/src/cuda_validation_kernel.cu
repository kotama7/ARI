#include <cuda_runtime.h>

#include <algorithm>
#include <cmath>
#include <cstddef>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <limits>
#include <string>
#include <vector>

namespace {

__global__ void vector_add(const float* left, const float* right, float* output,
                           std::size_t count) {
  const std::size_t index = blockIdx.x * blockDim.x + threadIdx.x;
  if (index < count) {
    output[index] = left[index] + right[index];
  }
}

void require_cuda(cudaError_t status, const char* operation) {
  if (status != cudaSuccess) {
    std::cerr << "CUDA operation failed: " << operation << "\n";
    std::exit(2);
  }
}

std::string json_escape(const char* value) {
  std::string output;
  for (const unsigned char character : std::string(value)) {
    if (character == '"' || character == '\\') {
      output.push_back('\\');
      output.push_back(static_cast<char>(character));
    } else if (character >= 0x20) {
      output.push_back(static_cast<char>(character));
    }
  }
  return output;
}

struct DeviceResult {
  int index;
  std::string name;
  int major;
  int minor;
  std::size_t memory_bytes;
  std::size_t case_count;
  double maximum_absolute_error;
  double checksum;
  bool repeated_execution_equal;
  bool negative_control_detected;
};

DeviceResult validate_device(int device) {
  require_cuda(cudaSetDevice(device), "cudaSetDevice");
  cudaDeviceProp properties{};
  require_cuda(cudaGetDeviceProperties(&properties, device),
               "cudaGetDeviceProperties");

  const std::vector<std::size_t> sizes = {1, 257, 65537, 1048576};
  double maximum_error = 0.0;
  double aggregate_checksum = 0.0;
  bool repeated_equal = true;
  bool negative_detected = true;

  for (const std::size_t count : sizes) {
    std::vector<float> left(count);
    std::vector<float> right(count);
    std::vector<float> first(count);
    std::vector<float> second(count);
    for (std::size_t index = 0; index < count; ++index) {
      left[index] = static_cast<float>(static_cast<int>(index % 251) - 125) /
                    17.0F;
      right[index] = static_cast<float>(static_cast<int>(index % 127) - 63) /
                     19.0F;
    }

    float* device_left = nullptr;
    float* device_right = nullptr;
    float* device_output = nullptr;
    const std::size_t bytes = count * sizeof(float);
    require_cuda(cudaMalloc(&device_left, bytes), "cudaMalloc(left)");
    require_cuda(cudaMalloc(&device_right, bytes), "cudaMalloc(right)");
    require_cuda(cudaMalloc(&device_output, bytes), "cudaMalloc(output)");
    require_cuda(cudaMemcpy(device_left, left.data(), bytes,
                            cudaMemcpyHostToDevice),
                 "cudaMemcpy(left)");
    require_cuda(cudaMemcpy(device_right, right.data(), bytes,
                            cudaMemcpyHostToDevice),
                 "cudaMemcpy(right)");

    for (int repeat = 0; repeat < 2; ++repeat) {
      const int threads = 256;
      const int blocks = static_cast<int>((count + threads - 1) / threads);
      vector_add<<<blocks, threads>>>(device_left, device_right, device_output,
                                      count);
      require_cuda(cudaGetLastError(), "vector_add launch");
      require_cuda(cudaDeviceSynchronize(), "vector_add synchronize");
      std::vector<float>& observed = repeat == 0 ? first : second;
      require_cuda(cudaMemcpy(observed.data(), device_output, bytes,
                              cudaMemcpyDeviceToHost),
                   "cudaMemcpy(output)");
    }

    for (std::size_t index = 0; index < count; ++index) {
      const float expected = left[index] + right[index];
      maximum_error = std::max(
          maximum_error,
          std::abs(static_cast<double>(first[index]) - expected));
      aggregate_checksum += static_cast<double>(first[index]);
      repeated_equal = repeated_equal && first[index] == second[index];
    }
    std::vector<float> corrupted = first;
    corrupted[count / 2] += 1.0F;
    bool corrupted_rejected = false;
    for (std::size_t index = 0; index < count; ++index) {
      const float expected = left[index] + right[index];
      if (std::abs(static_cast<double>(corrupted[index]) - expected) > 1e-6) {
        corrupted_rejected = true;
        break;
      }
    }
    negative_detected = negative_detected && corrupted_rejected;

    require_cuda(cudaFree(device_output), "cudaFree(output)");
    require_cuda(cudaFree(device_right), "cudaFree(right)");
    require_cuda(cudaFree(device_left), "cudaFree(left)");
  }

  return DeviceResult{device,
                      json_escape(properties.name),
                      properties.major,
                      properties.minor,
                      properties.totalGlobalMem,
                      sizes.size(),
                      maximum_error,
                      aggregate_checksum,
                      repeated_equal,
                      negative_detected};
}

}  // namespace

int main() {
  int device_count = 0;
  require_cuda(cudaGetDeviceCount(&device_count), "cudaGetDeviceCount");
  if (device_count <= 0) {
    std::cerr << "CUDA validation found no devices\n";
    return 3;
  }
  std::vector<DeviceResult> results;
  bool passed = true;
  for (int device = 0; device < device_count; ++device) {
    DeviceResult result = validate_device(device);
    passed = passed && result.maximum_absolute_error <= 1e-6 &&
             result.repeated_execution_equal && result.negative_control_detected;
    results.push_back(result);
  }

  std::cout << std::setprecision(17)
            << "{\"schema_version\":\"ari.cuda-self-test/v1\","
            << "\"verdict\":\"" << (passed ? "pass" : "fail") << "\","
            << "\"device_count\":" << device_count << ",\"devices\":[";
  for (std::size_t index = 0; index < results.size(); ++index) {
    if (index) std::cout << ',';
    const DeviceResult& item = results[index];
    std::cout << "{\"device_index\":" << item.index << ",\"name\":\""
              << item.name << "\",\"compute_capability\":\"" << item.major
              << '.' << item.minor << "\",\"memory_bytes\":"
              << item.memory_bytes << ",\"case_count\":" << item.case_count
              << ",\"maximum_absolute_error\":"
              << item.maximum_absolute_error << ",\"checksum\":"
              << item.checksum << ",\"repeated_execution_equal\":"
              << (item.repeated_execution_equal ? "true" : "false")
              << ",\"negative_control_detected\":"
              << (item.negative_control_detected ? "true" : "false") << '}';
  }
  std::cout << "]}\n";
  return passed ? 0 : 4;
}
