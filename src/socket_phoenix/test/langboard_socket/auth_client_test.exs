defmodule LangboardSocket.AuthClientTest do
  use ExUnit.Case, async: true

  alias LangboardSocket.AuthClient

  @internal_secret String.duplicate("s", 32)

  test "readiness requires the current internal API contract" do
    for {status, body, expected} <- [
          {200, ~s({"contract_version":1}), true},
          {200, ~s({"contract_version":0}), false},
          {200, ~s({"contract_version":"1"}), false},
          {404, "{}", false}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        assert conn.method == "GET"
        assert conn.request_path == "/auth/socket/capabilities"
        assert Plug.Conn.get_req_header(conn, "x-socket-internal-secret") == [@internal_secret]

        conn
        |> Plug.Conn.put_resp_content_type("application/json")
        |> Plug.Conn.send_resp(status, body)
      end)

      assert AuthClient.ready?(
               internal_secret: @internal_secret,
               plug: {Req.Test, __MODULE__}
             ) == expected
    end

    refute AuthClient.ready?(internal_secret: "short")
  end

  test "JSON socket authorization distinguishes expiry from invalid credentials" do
    for {status, body, expected} <- [
          {401, ~s({"code":"AU1004"}), {:error, :expired_token}},
          {401, "{}", {:error, :unauthorized}},
          {503, "{}", {:error, :unavailable}}
        ],
        path <- ["/auth/socket", "/auth/socket/subscriptions"] do
      Req.Test.expect(__MODULE__, fn conn ->
        assert conn.request_path == path
        assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]

        conn
        |> Plug.Conn.put_resp_content_type("application/json")
        |> Plug.Conn.send_resp(status, body)
      end)

      result =
        if path == "/auth/socket" do
          AuthClient.authenticate("access-token", plug: {Req.Test, __MODULE__})
        else
          AuthClient.authorize_subscriptions("access-token", "board", ["board-uid"],
            plug: {Req.Test, __MODULE__}
          )
        end

      assert result == expected
    end
  end

  test "editor authorization forwards the token and document name" do
    handler_id = {__MODULE__, self(), make_ref()}

    :ok =
      :telemetry.attach(
        handler_id,
        [:langboard_socket, :authorization, :request],
        fn _event, measurements, metadata, owner ->
          send(owner, {:authorization_request, measurements, metadata})
        end,
        self()
      )

    on_exit(fn -> :telemetry.detach(handler_id) end)

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.method == "POST"
      assert conn.request_path == "/auth/socket/editor-document"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert {:ok, body, _conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"document_name" => "card:card-uid:description"}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(
        200,
        ~s({"authorized":true,"user_name":"Verified Editor","writable":true})
      )
    end)

    assert {:ok, "Verified Editor", true} =
             AuthClient.authorize_editor_document("access-token", "card:card-uid:description",
               plug: {Req.Test, __MODULE__}
             )

    assert_receive {:authorization_request, %{count: 1, duration_microseconds: duration},
                    metadata}

    assert duration >= 0
    assert metadata == %{route: "/auth/socket/editor-document", result: :success}
    refute inspect(metadata) =~ "access-token"
    refute inspect(metadata) =~ "card-uid"
  end

  test "denial, authentication failure, and backend failure remain distinct" do
    for {status, body, expected} <- [
          {200, ~s({"authorized":false,"user_name":null,"writable":false}), {:error, :forbidden}},
          {200, ~s({"authorized":true,"user_name":"Editor"}), {:error, :unavailable}},
          {401, "{}", {:error, :unauthorized}},
          {500, "{}", {:error, :unavailable}}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        conn
        |> Plug.Conn.put_resp_content_type("application/json")
        |> Plug.Conn.send_resp(status, body)
      end)

      assert ^expected =
               AuthClient.authorize_editor_document("access-token", "card:card-uid",
                 plug: {Req.Test, __MODULE__}
               )
    end

    assert {:error, :unauthorized} = AuthClient.authorize_editor_document(nil, "card:card-uid")
  end

  test "editor authorization reports a successful HTTP response with an invalid contract" do
    handler_id = {__MODULE__, self(), make_ref()}

    :ok =
      :telemetry.attach(
        handler_id,
        [:langboard_socket, :authorization, :request],
        fn _event, measurements, metadata, owner ->
          send(owner, {:authorization_request, measurements, metadata})
        end,
        self()
      )

    on_exit(fn -> :telemetry.detach(handler_id) end)

    Req.Test.expect(__MODULE__, fn conn ->
      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"authorized":true,"user_name":"Editor"}))
    end)

    assert {:error, :unavailable} =
             AuthClient.authorize_editor_document("access-token", "card:card-uid",
               plug: {Req.Test, __MODULE__}
             )

    assert_receive {:authorization_request, %{count: 1}, metadata}
    assert metadata == %{route: "/auth/socket/editor-document", result: :invalid_response}
  end

  test "editor HTTP authorization forwards the existing internal token" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-http-document"
      assert Plug.Conn.get_req_header(conn, "x-api-token") == ["internal-token"]
      assert Plug.Conn.get_req_header(conn, "authorization") == []
      assert {:ok, body, _conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"document_name" => "card:card-uid", "write" => true}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"authorized":true}))
    end)

    assert {:ok, true} =
             AuthClient.authorize_editor_http_document(
               {:api_token, "internal-token"},
               "card:card-uid",
               write: true,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "editor HTTP authorization forwards a bearer token with its refresh cookie" do
    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-http-document"
      assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
      assert Plug.Conn.get_req_header(conn, "cookie") == ["refresh=value"]
      assert {:ok, body, _conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"document_name" => "card:card-uid", "write" => false}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"authorized":false}))
    end)

    assert {:ok, false} =
             AuthClient.authorize_editor_http_document(
               {:bearer, "access-token", "refresh=value"},
               "card:card-uid",
               plug: {Req.Test, __MODULE__}
             )

    assert {:error, :unauthorized} =
             AuthClient.authorize_editor_http_document(
               {:bearer, "access-token", ""},
               "card:card-uid"
             )
  end

  test "batched editor HTTP authorization forwards all names and the existing credentials" do
    names = ["card:first", "card:second"]

    Req.Test.expect(__MODULE__, fn conn ->
      assert conn.request_path == "/auth/socket/editor-http-documents"
      assert Plug.Conn.get_req_header(conn, "x-api-token") == ["internal-token"]
      assert {:ok, body, _conn} = Plug.Conn.read_body(conn)
      assert Jason.decode!(body) == %{"document_names" => names, "write" => false}

      conn
      |> Plug.Conn.put_resp_content_type("application/json")
      |> Plug.Conn.send_resp(200, ~s({"authorized":true}))
    end)

    assert {:ok, true} =
             AuthClient.authorize_editor_http_documents(
               {:api_token, "internal-token"},
               names,
               plug: {Req.Test, __MODULE__}
             )
  end

  test "batched editor HTTP authorization preserves denial, authentication, and failure" do
    for {status, body, expected} <- [
          {200, ~s({"authorized":false}), {:ok, false}},
          {401, "{}", {:error, :unauthorized}},
          {500, "{}", {:error, :unavailable}},
          {200, ~s({"authorized":"true"}), {:error, :unavailable}}
        ] do
      Req.Test.expect(__MODULE__, fn conn ->
        assert Plug.Conn.get_req_header(conn, "authorization") == ["Bearer access-token"]
        assert Plug.Conn.get_req_header(conn, "cookie") == ["refresh=value"]

        conn
        |> Plug.Conn.put_resp_content_type("application/json")
        |> Plug.Conn.send_resp(status, body)
      end)

      assert ^expected =
               AuthClient.authorize_editor_http_documents(
                 {:bearer, "access-token", "refresh=value"},
                 ["card:first"],
                 plug: {Req.Test, __MODULE__}
               )
    end

    assert {:error, :unauthorized} = AuthClient.authorize_editor_http_documents(nil, [])
  end
end
