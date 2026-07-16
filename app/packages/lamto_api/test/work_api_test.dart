import 'package:test/test.dart';
import 'package:lamto_api/lamto_api.dart';


/// tests for WorkApi
void main() {
  final instance = LamtoApi().getWorkApi();

  group(WorkApi, () {
    //Future<WorkRatingResult> workRatingCreate(int id, WorkRatingRequest workRatingRequest) async
    test('test workRatingCreate', () async {
      // TODO
    });

  });
}
