import 'package:dio/dio.dart';
import '../gate_repository.dart';
class ReaderRepository {
  ReaderRepository(this.dio, this.credential);
  final Dio dio; final String credential;
  Future<Response<dynamic>> recognizePlate(String plate) => dio.post(GateApiPaths.recognizePlate, data: {'plate': plate}, options: Options(headers: {'Authorization': 'GateDevice $credential'}));
  Future<Response<dynamic>> recognizeFace(String path) => dio.post(GateApiPaths.recognizeFace, data: FormData.fromMap({'photo': MultipartFile.fromFileSync(path)}), options: Options(headers: {'Authorization': 'GateDevice $credential'}));
}
